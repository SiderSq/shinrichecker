"""Offline coverage for pooled requests, bounded OCR reuse and image regions."""

import base64
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from PIL import Image
from shinri_ranker.client import ShinriClient, ShinriNetworkError
from shinri_ranker.ocr import OcrProcessor, OcrUnavailable
from shinri_ranker.server import create_server
from shinri_ranker.cache import TTLCache


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.hits += 1
        status, body = 200, b'{"ok": true}'
        if self.path == "/missing":
            status = 404
        elif self.path == "/bad":
            body = b"not json"
        elif self.path == "/empty":
            status, body = 204, b""
        elif self.path in ("/redirect", "/foreign"):
            status, body = 302, b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if self.path == "/redirect":
            self.send_header("Location", "/ok")
        if self.path == "/foreign":
            self.send_header("Location", "https://foreign.invalid/")
        self.end_headers()
        self.wfile.write(body)


class CountingServer(ThreadingHTTPServer):
    def get_request(self):
        connection = super().get_request()
        self.accepted += 1
        return connection


class TestPooledRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = CountingServer(("127.0.0.1", 0), FixtureHandler)
        cls.server.accepted = cls.server.hits = 0
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        self.client = ShinriClient(delay_between_requests=0)
        self.addCleanup(self.client.close)

    def test_reuses_one_tcp_connection_for_ten_requests(self):
        before = self.server.accepted
        for _ in range(10):
            self.assertEqual(self.client._http_get_json(self.url + "/ok"), {"ok": True})
        self.assertEqual(self.server.accepted - before, 1)

    def test_404_is_not_a_network_failure_and_connection_reusable(self):
        self.assertIsNone(self.client._http_get_json(self.url + "/missing"))
        before = self.server.accepted
        self.assertEqual(self.client._http_get_json(self.url + "/ok"), {"ok": True})
        self.assertEqual(self.server.accepted, before)

    def test_tls_certificate_verification_is_required(self):
        import ssl

        pool = self.client._transport._direct.connection_from_url("https://shinrireviews.com")
        self.assertEqual(pool.cert_reqs, ssl.CERT_REQUIRED)

    def test_empty_response(self):
        self.assertIsNone(self.client._http_get_json(self.url + "/empty"))

    def test_same_origin_redirect_reuses_connection(self):
        self.assertEqual(self.client._http_get_json(self.url + "/redirect"), {"ok": True})

    def test_cross_origin_redirect_rejected(self):
        with self.assertRaises(ShinriNetworkError):
            self.client._http_get_json(self.url + "/foreign", max_retries=1)

    def test_malformed_json_not_retried(self):
        before = self.server.hits
        with self.assertRaises(ShinriNetworkError):
            self.client._http_get_json(self.url + "/bad")
        self.assertEqual(self.server.hits - before, 1)

    def test_expired_budget_never_sends_request(self):
        before = self.server.hits
        with self.client.lookup_deadline(time.monotonic() - 1):
            with self.assertRaises(ShinriNetworkError):
                self.client._http_get_json(self.url + "/ok", max_retries=1)
        self.assertEqual(self.server.hits, before)

    def test_offline_never_opens_connection(self):
        self.client.offline_mode = True
        with patch.object(self.client._transport, "get") as request:
            with self.assertRaises(ShinriNetworkError):
                self.client._http_get_json(self.url + "/ok")
            request.assert_not_called()

    def test_proxy_is_reused_and_respects_bypass(self):
        transport = self.client._transport
        transport._environment = {"https": "http://proxy.example:8080"}
        with patch("shinri_ranker.transport.urllib.request.proxy_bypass", return_value=False):
            manager = transport._manager("https://example.com")
            self.assertIs(transport._manager("https://example.com/other"), manager)
        with patch("shinri_ranker.transport.urllib.request.proxy_bypass", return_value=True):
            self.assertIs(transport._manager("https://example.com"), transport._direct)

    def test_network_failure_retries_with_existing_client_policy(self):
        with (
            patch.object(
                self.client._transport,
                "get",
                side_effect=[URLError("closed"), (200, b'{"ok":true}')],
            ) as get,
            patch("shinri_ranker.client.time.sleep"),
        ):
            self.assertEqual(self.client._http_get_json(self.url + "/ok"), {"ok": True})
            self.assertEqual(get.call_count, 2)


class TestOcrRegion(unittest.TestCase):
    def test_exact_normalized_rectangle(self):
        image = Image.new("RGB", (200, 100), "black")
        image.paste("white", (50, 20, 150, 80))
        cropped = OcrProcessor.crop_region(
            image, {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.6}
        )
        self.assertEqual(cropped.size, (100, 60))
        self.assertEqual(cropped.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(image.size, (200, 100))

    def test_full_image_default(self):
        image = Image.new("RGB", (200, 100))
        self.assertIs(OcrProcessor.crop_region(image, None), image)

    def test_invalid_regions(self):
        for roi in [
            {},
            {"x": True, "y": 0, "width": 1, "height": 1},
            {"x": 0, "y": 0, "width": float("nan"), "height": 1},
            {"x": 0.9, "y": 0, "width": 0.2, "height": 1},
            {"x": 0, "y": 0, "width": 0, "height": 1},
        ]:
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                OcrProcessor.validate_roi(roi)

    def test_too_small_region_rejected(self):
        with self.assertRaises(ValueError):
            OcrProcessor.crop_region(
                Image.new("RGB", (100, 100)), {"x": 0, "y": 0, "width": 0.01, "height": 0.01}
            )

    def test_process_crops_before_recognition(self):
        image = Image.new("RGB", (200, 100))
        with (
            patch("shinri_ranker.ocr.HAS_WINRT_OCR", True),
            patch.object(OcrProcessor, "recognize_native", return_value="Hunk") as recognize,
            patch.object(OcrProcessor, "process_screenshot_text", return_value=[]),
        ):
            OcrProcessor.process_image(
                image,
                ShinriClient(offline_mode=True),
                layout="text",
                roi={"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.6},
            )
        self.assertEqual(recognize.call_args.args[0].size, (100, 60))


class TestOcrImageCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.client = ShinriClient(
            cache_path=str(Path(cls.directory.name) / "cache.json"), offline_mode=True
        )
        cls.client._populate_indexes([{"playerId": 1, "playerName": "Hunk", "avg": 4, "count": 10}])
        cls.server = create_server(port=0, client=cls.client)
        cls.token = cls.server.RequestHandlerClass.api_token
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api/ocr-process"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        buffer = io.BytesIO()
        Image.new("RGB", (200, 100)).save(buffer, format="PNG")
        cls.image = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.client.close()
        cls.thread.join(2)
        cls.directory.cleanup()

    def setUp(self):
        self.server.RequestHandlerClass.ocr_cache.clear()

    def request(self, **overrides):
        data = {"image": self.image, "layout": "text", **overrides}
        request = Request(
            self.url,
            data=json.dumps(data).encode(),
            headers={"X-Shinri-Token": self.token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def result(self):
        return "Hunk", [
            {"matched_name": "Hunk", "raw_ocr": "Hunk", "player_id": 1, "needs_review": False}
        ]

    def test_repeated_image_skips_engine_and_returns_fresh_result(self):
        with patch.object(OcrProcessor, "process_image", return_value=self.result()) as engine:
            first = self.request()[1]
            second = self.request()[1]
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            first["candidates"][0]["confirmed"] = True
            self.assertNotIn("confirmed", self.request()[1]["candidates"][0])
            self.assertEqual(engine.call_count, 1)

    def test_database_generation_invalidates(self):
        with patch.object(OcrProcessor, "process_image", return_value=self.result()) as engine:
            self.request()
            self.client._populate_indexes(
                [{"playerId": 1, "playerName": "Hunk", "avg": 3, "count": 11}]
            )
            self.assertFalse(self.request()[1]["cache_hit"])
            self.assertEqual(engine.call_count, 2)

    def test_layout_roi_and_image_are_separate_keys(self):
        with patch.object(OcrProcessor, "process_image", return_value=self.result()) as engine:
            self.request()
            self.request(layout="auto")
            self.request(roi={"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8})
            self.assertEqual(engine.call_count, 3)

    def test_failures_not_cached(self):
        with patch.object(
            OcrProcessor, "process_image", side_effect=OcrUnavailable("Нет движка")
        ) as engine:
            self.assertEqual(self.request()[0], 503)
            self.assertEqual(self.request()[0], 503)
            self.assertEqual(engine.call_count, 2)

    def test_invalid_roi_rejected_before_engine(self):
        with patch.object(OcrProcessor, "process_image") as engine:
            self.assertEqual(self.request(roi={"x": 0, "y": 0, "width": 2, "height": 1})[0], 400)
            engine.assert_not_called()

    def test_memory_cache_is_bounded_and_expires(self):
        cache = TTLCache(ttl=0.01, maxsize=2)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        self.assertIsNone(cache.get("a"))
        time.sleep(0.02)
        self.assertIsNone(cache.get("b"))
        self.assertIsNone(cache.get("c"))
