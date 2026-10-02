"""Offline regressions for security, cache consistency and OCR review contracts."""

import base64
import io
import json
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from PIL import Image
from shinri_ranker.analytics import TeamBalancer, TournamentGenerator, SentimentAnalyzer
from shinri_ranker.cache import TTLCache
from shinri_ranker.client import ShinriClient, ShinriNetworkError
from shinri_ranker.fuzzy import FuzzyMatcher
from shinri_ranker.matcher import InputParser, ProfileMatcher, MatchStatus
from shinri_ranker.ocr import OcrProcessor, OcrUnavailable
from shinri_ranker.ranker import Ranker
from shinri_ranker.server import create_server


def ratings(n=4):
    return [
        {"playerId": i, "playerName": f"Player{i}", "avg": 4.0, "count": i} for i in range(1, n + 1)
    ]


class TestDataIntegrity(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = ShinriClient(
            cache_path=str(Path(self.directory.name) / "cache.json"), offline_mode=True
        )
        self.client._populate_indexes(ratings())

    def test_hash_ids_in_text_and_csv(self):
        self.assertEqual(
            [i.extracted_id for i in InputParser.parse_text("#1\n# 2\n# comment")], [1, 2]
        )
        self.assertEqual(
            [i.extracted_id for i in InputParser.parse_text("id,name\n#1,Player1\n#2,Player2")],
            [1, 2],
        )

    def test_analytics_uses_unique_full_roster(self):
        results = ProfileMatcher(self.client).process_items(
            InputParser.parse_text("1\n2\n3\n4\n1"), allow_online=False
        )
        report = Ranker.generate_report(results, top_n=1)
        self.assertEqual(len(report.best_players), 1)
        self.assertEqual(len(report.analytics_roster()), 4)

    def test_failed_import_preserves_live_indexes(self):
        snapshot = deepcopy(self.client._by_id)
        with self.assertRaises(ValueError):
            self.client.import_ratings(ratings() + [{"playerId": "bad"}])
        self.assertEqual(snapshot, self.client._by_id)

    def test_failed_save_does_not_publish_import(self):
        with patch.object(self.client, "_write_cache_file", side_effect=OSError("read only")):
            with self.assertRaises(OSError):
                self.client.import_ratings(ratings(8))
        self.assertEqual(len(self.client._by_id), 4)

    def test_empty_database_is_initialized(self):
        self.client._populate_indexes([])
        self.assertTrue(self.client.is_loaded)
        self.assertIsNone(self.client.find_by_id(1))
        self.assertEqual(self.client.global_avg_rating, 4.8)

    def test_cache_round_trip_and_corrupt_sidecar(self):
        self.client.import_ratings(ratings())
        self.assertEqual(len(self.client._read_cache_file()["ratings"]), 4)
        Path(self.client.cache_path + ".dat").write_bytes(b"broken sidecar")
        self.assertEqual(len(self.client._read_cache_file()["ratings"]), 4)
        Path(self.client.cache_path).write_text("{bad json")
        self.assertIsNone(self.client._read_cache_file())

    def test_refresh_keeps_directory_and_name_changes(self):
        self.client.offline_mode = False

        def api(url):
            if url.endswith("/ratings"):
                return [{"playerId": 1, "playerName": "Player1", "avg": 5.0, "count": 3}]
            return [[1, "Renamed"], [2, "Newcomer"]]

        with patch.object(self.client, "_http_get_json", side_effect=api):
            delta = self.client.refresh_delta()
        self.assertEqual(self.client.find_by_id(2)["count"], 0)
        self.assertEqual(self.client.find_by_id(1)["name"], "Renamed")
        self.assertEqual(delta["removed"], 2)

    def test_fuzzy_invalidates_before_returning_cached_query(self):
        self.client._populate_indexes(
            [{"playerId": 1, "playerName": "FallenAngel", "avg": 4.0, "count": 1}]
        )
        fuzzy = FuzzyMatcher(self.client)
        self.assertIsNotNone(fuzzy.find_best_match("FallenAnge1"))
        self.client._populate_indexes(
            [{"playerId": 2, "playerName": "Other", "avg": 4.0, "count": 1}]
        )
        self.assertIsNone(fuzzy.find_best_match("FallenAnge1"))

    def test_network_failure_is_not_negative_cached(self):
        self.client.offline_mode = False
        with patch.object(
            self.client, "_http_get_json", side_effect=ShinriNetworkError("temporary")
        ):
            with self.assertRaises(ShinriNetworkError):
                self.client.fetch_player_online_by_name("Absent")
        self.assertNotIn("absent", self.client._negative_name_cache)

    def test_missing_review_response_does_not_mean_unrated(self):
        self.client.offline_mode = False
        with patch.object(
            self.client,
            "_http_get_json",
            side_effect=[{"id": 99, "name": "Known"}, ShinriNetworkError("temporary")],
        ):
            with self.assertRaises(ShinriNetworkError):
                self.client.fetch_player_online_by_id(99)
        self.assertNotIn(99, self.client._online_id_cache)

    def test_negative_cache_expires(self):
        cache = TTLCache(ttl=0.001, maxsize=2)
        cache.add("name")
        time.sleep(0.01)
        self.assertNotIn("name", cache)
        for i in range(3):
            cache[i] = i
        self.assertNotIn(0, cache)

    def test_rank_configuration_rejected(self):
        with self.assertRaises(ValueError):
            Ranker.calculate_bayesian_score(4, 2, m=-2)
        with self.assertRaises(ValueError):
            Ranker.generate_report([], top_n=-1)

    def test_tournament_preserves_every_participant(self):
        for n in (2, 3, 5, 7, 9, 17, 32, 33):
            players = [{"player_id": i, "name": f"P{i}", "avg_rating": 4.0} for i in range(n)]
            knockout = TournamentGenerator.generate_single_elimination(players)
            ids = [
                p["player_id"]
                for m in knockout["matches"]
                for p in (m["player_1"], m["player_2"])
                if p
            ]
            self.assertCountEqual(ids, range(n))
            grouped = TournamentGenerator.generate_round_robin(players)
            ids = [p["player_id"] for g in grouped["groups"].values() for p in g["players"]]
            self.assertCountEqual(ids, range(n))

    def test_balancer_does_not_mutate_input(self):
        players = [{"name": f"P{i}", "avg_rating": 4.0 + i / 10} for i in range(5)]
        before = deepcopy(players)
        result = TeamBalancer.balance_teams(players)
        self.assertEqual(before, players)
        self.assertEqual(sorted([len(result["team_a"]), len(result["team_b"])]), [2, 3])

    def test_sentiment_negation_is_not_toxic_hit(self):
        self.assertEqual(
            SentimentAnalyzer.analyze_reviews([{"text": "не токсичный"}])["neg_hits"], 0
        )


class TestOcrContracts(unittest.TestCase):
    def setUp(self):
        self.client = ShinriClient(offline_mode=True)
        self.client._populate_indexes(
            [
                {"playerId": 1, "playerName": "FallenAngel", "avg": 4.0, "count": 10},
                {"playerId": 2, "playerName": "Alex", "avg": 4.0, "count": 10},
                {"playerId": 3, "playerName": "Alex", "avg": 3.0, "count": 5},
            ]
        )

    def test_homonym_requires_review_and_keeps_alternatives(self):
        candidate = OcrProcessor.process_screenshot_text("Alex", self.client)[0]
        self.assertTrue(candidate["needs_review"])
        self.assertEqual({a["id"] for a in candidate["alternatives"]}, {2, 3})

    def test_strong_unique_correction_and_raw_text(self):
        candidate = OcrProcessor.process_screenshot_text("FallenAnge1", self.client)[0]
        self.assertEqual(candidate["raw_ocr"], "FallenAnge1")
        self.assertEqual(candidate["player_id"], 1)
        self.assertFalse(candidate["needs_review"])

    def test_unknown_requires_confirmation(self):
        result = OcrProcessor.process_screenshot_text("Unknown999", self.client)
        self.assertTrue(result[0]["needs_review"])
        self.assertIsNone(result[0]["player_id"])

    def test_weak_correction_requires_review(self):
        candidate = {
            "raw_ocr": "FallenZZZel",
            "matched_name": "FallenAngel",
            "similarity": 0.75,
            "corrected": True,
            "player_id": 1,
        }
        self.assertTrue(
            OcrProcessor.annotate_candidates([candidate], self.client)[0]["needs_review"]
        )

    def test_reject_invalid_base64(self):
        with self.assertRaises(ValueError):
            OcrProcessor.load_image("data:image/png;base64,***")

    def test_reject_oversized_dimensions(self):
        with self.assertRaises(ValueError):
            OcrProcessor.load_image(Image.new("L", (12001, 1)))

    def test_transparency_and_orientation_normalization(self):
        image = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        decoded = OcrProcessor.load_image(buffer.getvalue())
        self.assertEqual(decoded.getpixel((0, 0)), (255, 255, 255))

    def test_missing_engine_is_explicit(self):
        with (
            patch("shinri_ranker.ocr.HAS_WINRT_OCR", False),
            patch.object(OcrProcessor, "tesseract_languages", return_value=()),
        ):
            with self.assertRaises(OcrUnavailable):
                OcrProcessor.process_image(Image.new("RGB", (200, 200)), self.client)

    def test_expired_ocr_budget_stops_processing(self):
        from shinri_ranker.ocr import _ENGINE_STATE

        previous = getattr(_ENGINE_STATE, "deadline", None)
        _ENGINE_STATE.deadline = time.monotonic() - 1
        try:
            with self.assertRaises(TimeoutError):
                OcrProcessor._remaining_budget()
        finally:
            _ENGINE_STATE.deadline = previous

    def test_tesseract_fallback_contract(self):
        from subprocess import CompletedProcess

        with (
            patch.object(OcrProcessor, "tesseract_languages", return_value=("eng",)),
            patch("shinri_ranker.ocr.shutil.which", return_value="/usr/bin/tesseract"),
            patch(
                "shinri_ranker.ocr.subprocess.run",
                return_value=CompletedProcess([], 0, b"FallenAngel", b""),
            ) as process,
        ):
            self.assertEqual(
                OcrProcessor._recognize_tesseract(Image.new("RGB", (200, 200))), "FallenAngel"
            )
            self.assertEqual(process.call_args.kwargs["timeout"], 12)


class TestHttpBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.static = root / "static"
        cls.static.mkdir()
        (cls.static / "index.html").write_text("<head><!--SHINRI_BOOTSTRAP--></head>")
        (root / "secret.txt").write_text("not public")
        cls.client = ShinriClient(cache_path=str(root / "cache.json"), offline_mode=True)
        cls.client._populate_indexes(ratings())
        cls.server = create_server(port=0, client=cls.client, static_dir=str(cls.static))
        cls.token = cls.server.RequestHandlerClass.api_token
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.directory.cleanup()

    def request(self, path, data=None, token=True, headers=None):
        merged = {"Content-Type": "application/json"}
        if token:
            merged["X-Shinri-Token"] = self.token
        merged.update(headers or {})
        req = Request(
            self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=merged,
        )
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, response.read(), response.headers
        except HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def test_html_bootstraps_token(self):
        status, body, headers = self.request("/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.token.encode(), body)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_requires_session_token(self):
        self.assertEqual(self.request("/api/status", token=False)[0], 403)
        self.assertEqual(self.request("/api/status")[0], 200)

    def test_foreign_origin_and_rebinding_host_rejected(self):
        self.assertEqual(
            self.request("/api/status", headers={"Origin": "https://evil.example"})[0], 403
        )
        self.assertEqual(self.request("/", headers={"Host": "evil.example"})[0], 403)

    def test_no_universal_cors(self):
        self.assertIsNone(self.request("/api/status")[2].get("Access-Control-Allow-Origin"))

    def test_directory_traversal_rejected(self):
        for path in (
            "/static/../secret.txt",
            "/static/%2e%2e/secret.txt",
            "/static/..%5csecret.txt",
        ):
            status, body, _ = self.request(path)
            self.assertEqual(status, 404)
            self.assertNotIn(b"not public", body)

    def test_symlink_escape_rejected(self):
        try:
            (self.static / "link.txt").symlink_to(self.static.parent / "secret.txt")
        except FileExistsError:
            pass
        self.assertEqual(self.request("/static/link.txt")[0], 404)

    def test_invalid_json_shape_and_configuration(self):
        for data in (
            [],
            {"text": 4},
            {"text": "1", "m_confidence": -1},
            {"text": "1", "ranking_mode": "invalid"},
        ):
            self.assertEqual(self.request("/api/rank", data=data)[0], 400)

    def test_body_limit(self):
        req = Request(
            self.url + "/api/rank",
            data=b"",
            headers={
                "X-Shinri-Token": self.token,
                "Content-Type": "application/json",
                "Content-Length": str(13 * 1024 * 1024),
            },
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(req, timeout=3)
        self.assertEqual(error.exception.code, 413)

    def test_reject_local_ocr_paths(self):
        self.assertEqual(self.request("/api/ocr-process", data={"image": "/etc/passwd"})[0], 400)

    def test_duplicate_rows_do_not_form_valid_match(self):
        data = json.loads(self.request("/api/rank", data={"text": "\n".join(["1"] * 16)})[1])
        self.assertFalse(data["is_16_match"])
        self.assertEqual(data["participant_count"], 1)

    def test_safety_deduplicates_complete_roster_and_unrated(self):
        player = {"player_id": 99, "name": "Newcomer", "avg_rating": None, "reviews_count": 0}
        status, body, _ = self.request(
            "/api/lobby-safety", data={"players": [player], "unrated_players": [player]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["unrated_count"], 1)

    def test_refresh_and_status_still_work_offline(self):
        self.assertEqual(self.request("/api/refresh", data={})[0], 200)
        self.assertEqual(json.loads(self.request("/api/status")[1])["total_players"], 4)


if __name__ == "__main__":
    unittest.main()
