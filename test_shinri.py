"""
Automated unit and integration tests for Shinri Reviews Ranker.
"""

import json
import os
import tempfile
import unittest

from shinri_ranker.client import ShinriClient, ShinriNetworkError
from shinri_ranker.matcher import InputParser, MatchStatus, ProfileMatcher, ParseItem
from shinri_ranker.ranker import Ranker, RankedPlayer
from shinri_ranker.exporter import Exporter


class TestInputParser(unittest.TestCase):
    def test_parse_urls(self):
        urls = [
            "https://shinrireviews.com/p/3865",
            "http://shinrireviews.com/p/3865/",
            "shinrireviews.com/p/3865",
            "https://shinrireviews.com/#/p/3865",
            "p/3865",
        ]
        for url in urls:
            item = InputParser.parse_line(url)
            self.assertIsNotNone(item, f"Failed on {url}")
            self.assertEqual(item.extracted_id, 3865)

    def test_parse_numeric_ids(self):
        self.assertEqual(InputParser.parse_line("3865").extracted_id, 3865)
        self.assertEqual(InputParser.parse_line("#3865").extracted_id, 3865)

    def test_parse_names(self):
        item = InputParser.parse_line("mercyflower^-^")
        self.assertIsNotNone(item)
        self.assertIsNone(item.extracted_id)
        self.assertEqual(item.extracted_name, "mercyflower^-^")

    def test_ignore_empty_and_comments(self):
        self.assertIsNone(InputParser.parse_line(""))
        self.assertIsNone(InputParser.parse_line("   "))
        self.assertIsNone(InputParser.parse_line("# Comment"))
        self.assertIsNone(InputParser.parse_line("// Comment"))

    def test_parse_csv(self):
        csv_text = "Name,URL\nHunk,https://shinrireviews.com/p/3865\nmercyflower^-^,"
        items = InputParser.parse_text(csv_text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].extracted_id, 3865)
        self.assertEqual(items[1].extracted_name, "mercyflower^-^")

    def test_chat_log_extractor(self):
        log_sample = """
        [18:40:12] Hunk вошел в комнату
        Комната #14 (7/16): mercyflower^-^, cucumber, Bun|dimebag
        [18:41:00] FallenAngel: всем привет
        """
        items = InputParser.parse_text(log_sample, is_chat_log=True)
        names = [item.extracted_name for item in items]
        self.assertIn("Hunk", names)
        self.assertIn("mercyflower^-^", names)
        self.assertIn("cucumber", names)
        self.assertIn("Bun|dimebag", names)
        self.assertIn("FallenAngel", names)

    def test_avatar_mapping(self):
        url = ShinriClient.get_avatar_url("korekiyo_1")
        self.assertTrue(url.startswith("https://shinrireviews.com/assets/"))
        self.assertIn(".png", url)
        # Unknown should return default
        default_url = ShinriClient.get_avatar_url("unknown_character_xyz")
        self.assertIn("default", default_url)

    def test_bayesian_calculation(self):
        # 1 review of 5.0 vs 50 reviews of 4.90
        # With global_avg = 4.0, m = 5:
        score_1 = Ranker.calculate_bayesian_score(5.0, 1, global_avg=4.0, m=5)
        score_50 = Ranker.calculate_bayesian_score(4.90, 50, global_avg=4.0, m=5)
        # 50 reviews of 4.90 should beat 1 review of 5.0
        self.assertGreater(score_50, score_1)


class TestProfileMatcherAndRanker(unittest.TestCase):
    def setUp(self):
        self.mock_ratings = [
            {"playerId": 3865, "playerName": "Hunk", "count": 94, "avg": 5.0, "last": 1000},
            {"playerId": 37725, "playerName": "mercyflower^-^", "count": 62, "avg": 5.0, "last": 1000},
            {"playerId": 65995, "playerName": "Bun|dimebag", "count": 7, "avg": 1.0, "last": 1000},
            {"playerId": 35031, "playerName": "cucumber", "count": 3, "avg": 1.0, "last": 1000},
            {"playerId": 1001, "playerName": "MidPlayer", "count": 10, "avg": 3.5, "last": 1000},
            # Ambiguous players
            {"playerId": 35807, "playerName": "pssy", "count": 14, "avg": 5.0, "last": 1000},
            {"playerId": 51593, "playerName": "pssy", "count": 1, "avg": 5.0, "last": 1000},
        ]
        self.client = ShinriClient(offline_mode=True)
        self.client._populate_indexes(self.mock_ratings)

    def test_deduplication(self):
        matcher = ProfileMatcher(self.client)
        raw_items = [
            InputParser.parse_line("https://shinrireviews.com/p/3865", 1),
            InputParser.parse_line("Hunk", 2),
            InputParser.parse_line("3865", 3),
        ]
        results = matcher.process_items(raw_items)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].status, MatchStatus.MATCHED)
        self.assertEqual(results[1].status, MatchStatus.DUPLICATE)
        self.assertEqual(results[2].status, MatchStatus.DUPLICATE)
        self.assertEqual(results[1].duplicate_of_id, 3865)

    def test_ambiguous_most_reviews_strategy(self):
        matcher = ProfileMatcher(self.client)
        raw_items = [InputParser.parse_line("pssy", 1)]
        results = matcher.process_items(raw_items, resolve_ambiguous_strategy="most_reviews")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, MatchStatus.MATCHED)
        # Should pick ID 35807 with 14 reviews
        self.assertEqual(results[0].player_id, 35807)
        self.assertEqual(results[0].reviews_count, 14)

    def test_ambiguous_manual_strategy(self):
        matcher = ProfileMatcher(self.client)
        raw_items = [InputParser.parse_line("pssy", 1)]
        results = matcher.process_items(raw_items, resolve_ambiguous_strategy="manual")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, MatchStatus.AMBIGUOUS)
        self.assertEqual(len(results[0].candidates), 2)

    def test_missing_profile(self):
        matcher = ProfileMatcher(self.client)
        raw_items = [InputParser.parse_line("UnknownPlayer123", 1)]
        results = matcher.process_items(raw_items)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, MatchStatus.MISSING)

    def test_ranking_sort_order(self):
        matcher = ProfileMatcher(self.client)
        raw_items = [
            InputParser.parse_line("Hunk", 1),            # avg: 5.0, count: 94
            InputParser.parse_line("mercyflower^-^", 2),  # avg: 5.0, count: 62
            InputParser.parse_line("MidPlayer", 3),       # avg: 3.5, count: 10
            InputParser.parse_line("cucumber", 4),        # avg: 1.0, count: 3
            InputParser.parse_line("Bun|dimebag", 5),     # avg: 1.0, count: 7
        ]
        results = matcher.process_items(raw_items)
        report = Ranker.generate_report(results, top_n=2)

        # Best: 1st is Hunk (94 reviews), 2nd is mercyflower (62 reviews)
        self.assertEqual(len(report.best_players), 2)
        self.assertEqual(report.best_players[0].name, "Hunk")
        self.assertEqual(report.best_players[0].avg_rating, 5.0)
        self.assertEqual(report.best_players[1].name, "mercyflower^-^")

        # Worst: 1st worst is Bun|dimebag (avg 1.0, 7 reviews), 2nd worst is cucumber (avg 1.0, 3 reviews)
        self.assertEqual(len(report.worst_players), 2)
        self.assertEqual(report.worst_players[0].name, "Bun|dimebag")
        self.assertEqual(report.worst_players[0].avg_rating, 1.0)
        self.assertEqual(report.worst_players[1].name, "cucumber")

    def test_min_reviews_filter(self):
        matcher = ProfileMatcher(self.client)
        raw_items = [
            InputParser.parse_line("Bun|dimebag", 1), # count 7
            InputParser.parse_line("cucumber", 2),    # count 3
        ]
        results = matcher.process_items(raw_items)
        # min_reviews = 5: cucumber (3 reviews) should be excluded from ranked
        report = Ranker.generate_report(results, top_n=10, min_reviews=5)
        self.assertEqual(len(report.worst_players), 1)
        self.assertEqual(report.worst_players[0].name, "Bun|dimebag")
        self.assertEqual(len(report.unrated_players), 1)
        self.assertEqual(report.unrated_players[0].name, "cucumber")


class TestExporters(unittest.TestCase):
    def setUp(self):
        self.client = ShinriClient(offline_mode=True)
        self.client._populate_indexes([
            {"playerId": 3865, "playerName": "Hunk", "count": 94, "avg": 5.0, "last": 1000},
            {"playerId": 65995, "playerName": "Bun|dimebag", "count": 7, "avg": 1.0, "last": 1000},
        ])
        matcher = ProfileMatcher(self.client)
        raw_items = [
            InputParser.parse_line("Hunk", 1),
            InputParser.parse_line("Bun|dimebag", 2),
            InputParser.parse_line("Hunk", 3),  # duplicate
            InputParser.parse_line("NonExistent", 4),  # missing
        ]
        results = matcher.process_items(raw_items)
        self.report = Ranker.generate_report(results, top_n=5)

    def test_export_json(self):
        json_str = Exporter.to_json(self.report)
        data = json.loads(json_str)
        self.assertIn("best_players", data)
        self.assertIn("worst_players", data)
        self.assertEqual(len(data["best_players"]), 2)
        self.assertEqual(len(data["duplicates"]), 1)
        self.assertEqual(len(data["missing_players"]), 1)

    def test_export_csv(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".csv") as tmp:
            tmp_path = tmp.name

        try:
            csv_str = Exporter.to_csv(self.report, tmp_path)
            self.assertIn("ЛУЧШИЕ ИГРОКИ", csv_str)
            self.assertIn("ХУДШИЕ ИГРОКИ", csv_str)
            self.assertIn("Hunk", csv_str)
            self.assertIn("Bun|dimebag", csv_str)
            self.assertTrue(os.path.exists(tmp_path))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_export_markdown(self):
        md_str = Exporter.to_markdown(self.report)
        self.assertIn("Топ лучших игроков", md_str)
        self.assertIn("Антитоп (худшие игроки)", md_str)
        self.assertIn("Hunk", md_str)
        self.assertIn("Bun|dimebag", md_str)


class TestAnalyticsAndOcr(unittest.TestCase):
    def setUp(self):
        self.mock_ratings = [
            {"playerId": 3865, "playerName": "Hunk", "count": 94, "avg": 5.0, "last": 1000},
            {"playerId": 37725, "playerName": "mercyflower^-^", "count": 62, "avg": 5.0, "last": 1000},
            {"playerId": 65995, "playerName": "Bun|dimebag", "count": 7, "avg": 1.0, "last": 1000},
            {"playerId": 35031, "playerName": "cucumber", "count": 3, "avg": 1.0, "last": 1000},
            {"playerId": 1001, "playerName": "MidPlayer", "count": 10, "avg": 3.5, "last": 1000},
            {"playerId": 1002, "playerName": "GoodPlayer", "count": 15, "avg": 4.5, "last": 1000},
        ]
        self.client = ShinriClient(offline_mode=True)
        self.client._populate_indexes(self.mock_ratings)

    def test_team_balancer_equal_splits(self):
        from shinri_ranker.analytics import TeamBalancer
        players = [
            {"name": "P1", "bayesian_score": 5.0},
            {"name": "P2", "bayesian_score": 4.8},
            {"name": "P3", "bayesian_score": 2.5},
            {"name": "P4", "bayesian_score": 1.0},
        ]
        res = TeamBalancer.balance_teams(players, metric="bayesian_score")
        self.assertEqual(len(res["team_a"]), 2)
        self.assertEqual(len(res["team_b"]), 2)
        self.assertLessEqual(res["delta"], 1.0)
        self.assertGreaterEqual(res["fairness"], 80.0)

    def test_team_balancer_manual_roster_stats(self):
        from shinri_ranker.analytics import TeamBalancer
        team_a = [
            {"name": "A1", "bayesian_score": 5.0, "avg_rating": 5.0},
            {"name": "A2", "bayesian_score": 4.5, "avg_rating": 4.5},
        ]
        team_b = [
            {"name": "B1", "bayesian_score": 4.8, "avg_rating": 4.8},
            {"name": "B2", "bayesian_score": 4.7, "avg_rating": 4.7},
        ]
        res = TeamBalancer.calculate_roster_stats(team_a, team_b, metric="bayesian_score")
        self.assertEqual(len(res["team_a"]), 2)
        self.assertEqual(len(res["team_b"]), 2)
        self.assertAlmostEqual(res["avg_a"], 4.75, places=2)
        self.assertAlmostEqual(res["avg_b"], 4.75, places=2)
        self.assertEqual(res["delta"], 0.0)
        self.assertEqual(res["fairness"], 100.0)
        self.assertEqual(res["win_prob_a"], 50.0)
        self.assertEqual(res["win_prob_b"], 50.0)

    def test_lobby_safety_meter_safe_and_risk(self):
        from shinri_ranker.analytics import LobbySafetyMeter
        safe_ranked = [
            {"name": "Good1", "avg_rating": 4.9, "reviews_count": 20},
            {"name": "Good2", "avg_rating": 4.8, "reviews_count": 15},
        ]
        res_safe = LobbySafetyMeter.analyze_lobby(safe_ranked, [])
        self.assertEqual(res_safe["status"], "safe")
        self.assertGreaterEqual(res_safe["score"], 80)
        self.assertEqual(res_safe["danger_count"], 0)

        # Toxic / dangerous room
        danger_ranked = [
            {"name": "Troll1", "avg_rating": 1.0, "reviews_count": 5},
            {"name": "Troll2", "avg_rating": 1.2, "reviews_count": 8},
        ]
        res_risk = LobbySafetyMeter.analyze_lobby(danger_ranked, [{"name": "Newbie"}])
        self.assertEqual(res_risk["status"], "risk")
        self.assertLess(res_risk["score"], 60)
        self.assertEqual(res_risk["danger_count"], 2)
        self.assertEqual(res_risk["unrated_count"], 1)

    def test_ocr_token_cleaning(self):
        from shinri_ranker.ocr import OcrProcessor
        self.assertEqual(OcrProcessor.clean_ocr_token("[12:34:56] Hunk:"), "Hunk")
        self.assertEqual(OcrProcessor.clean_ocr_token("Pateti 120ms"), "Pateti")
        self.assertEqual(OcrProcessor.clean_ocr_token("#3865"), "3865")
        self.assertEqual(OcrProcessor.clean_ocr_token("<mercyflower^-^>"), "mercyflower^-^")

    def test_ocr_process_screenshot_text_and_fuzzy(self):
        from shinri_ranker.ocr import OcrProcessor
        # mercyfllower has typo, Hunk is exact, cucumber is exact
        text = "Hunk mercyfllower cucumber"
        candidates = OcrProcessor.process_screenshot_text(text, self.client, auto_fuzzy_correct=True)
        matched_names = [c["matched_name"] for c in candidates]
        self.assertIn("Hunk", matched_names)
        self.assertIn("mercyflower^-^", matched_names)
        self.assertIn("cucumber", matched_names)

        # Check typo correction flag
        mercy_cand = next(c for c in candidates if c["matched_name"] == "mercyflower^-^")
        self.assertTrue(mercy_cand["corrected"])
        self.assertEqual(mercy_cand["raw_ocr"], "mercyfllower")

    def test_ocr_image_preprocessing(self):
        from shinri_ranker.ocr import OcrProcessor
        from PIL import Image
        import io
        img = Image.new("RGB", (300, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        prep = OcrProcessor.preprocess_image(buf.getvalue())
        self.assertEqual(prep.mode, "L")
        # Upscaled to at least 1200px width
        self.assertGreaterEqual(prep.width, 1200)

    def test_ocr_character_subtitles_filter(self):
        from shinri_ranker.ocr import OcrProcessor
        subtitles = [
            "Кокичи Ома", "Сония Невермай", "Леон Кувата", "Бьякуя Тогами",
            "Рантаро Амами", "Химико Юмено", "Мукуро Икусаба", "Чиаки Нанами",
            "Кёко Киригири", "Ю-ВО", "Макото Наэги", "Микан Цумики", "Саяка Майзоно",
            "K0KM'-4V1", "Omar", "coma", "HeBepMaV1", "Neon", "Kasta",
            "6bAKYA", "ToraMY1", "PaHTapo", "ArqaMb•1", "XVIMVIKO", "}OMeH0",
            "MYKypo", "VIKyca6a", "quaKb•1", "Hag-larqn", "KéK0", "KupurupV1",
            "K1-BO", "Mak0oto0", "Haru", "Minka", "Cam«a", "MaV130H0"
        ]
        for sub in subtitles:
            self.assertTrue(
                OcrProcessor.is_danganronpa_character(sub),
                f"Failed to identify character subtitle: {sub}"
            )

        players = [
            "dinukio", "сельтипуд", "fzixnn", "Slayers", "Aggrest",
            "k-angelkawaii", "slicemyheart", "jabanessa", "еррукар",
            "Arestik", "Mood", "ворти", "илент1"
        ]
        for p in players:
            self.assertFalse(
                OcrProcessor.is_danganronpa_character(p),
                f"Player should not be flagged as character: {p}"
            )

    def test_ocr_dehomoglyph_and_recombine(self):
        from shinri_ranker.ocr import OcrProcessor
        user_ocr_text = """dinukio
K0KM'-4V1
Omar
cenbTunyA
coma
HeBepMaV1
fzixnn
Neon
Kasta
Slayers
6bAKYA
ToraMY1
Agg
forest
PaHTapo
ArqaMb•1
K-angelKawaii
XVIMVIKO
}OMeH0
slicemyheart
MYKypo
VIKyca6a
jab
amnesia
quaKb•1
Hag-larqn
eppYKap-[ABn1
KéK0
KupurupV1
Arestik
K1-BO
Monody
Mak0oto0
Haru
BOPTM
Minka
mneHT1
Cam«a
MaV130H0"""
        candidates = OcrProcessor.process_screenshot_text(user_ocr_text, self.client, auto_fuzzy_correct=True)
        # Should extract exactly 13 players
        self.assertEqual(len(candidates), 13)
        names = [c["matched_name"] for c in candidates]
        self.assertIn("dinukio", names)
        self.assertIn("fzixnn", names)
        self.assertIn("Slayers", names)
        self.assertIn("Aggrest", names)
        self.assertIn("K-angelKawaii", names)
        self.assertIn("slicemyheart", names)
        self.assertIn("jabanessa", names)
        self.assertIn("еррукар", names)
        self.assertIn("Arestik", names)
        self.assertIn("Monody", names)
        self.assertIn("ворти", names)
        self.assertIn("илент1", names)

    def test_clan_detector(self):
        from shinri_ranker.analytics import ClanDetector
        tag, clean = ClanDetector.extract_clan("[DR] Hunk")
        self.assertEqual(tag, "DR")
        self.assertEqual(clean, "Hunk")

        tag2, clean2 = ClanDetector.extract_clan("{TOP} Pateti")
        self.assertEqual(tag2, "TOP")
        self.assertEqual(clean2, "Pateti")

        tag3, clean3 = ClanDetector.extract_clan("cucumber")
        self.assertIsNone(tag3)
        self.assertEqual(clean3, "cucumber")

        # Test Russian Cyrillic clan tags
        tag_ru, clean_ru = ClanDetector.extract_clan("[РУС] Слава")
        self.assertEqual(tag_ru, "РУС")
        self.assertEqual(clean_ru, "Слава")

        # Test pipe format
        tag_pipe, clean_pipe = ClanDetector.extract_clan("Bun|dimebag")
        self.assertEqual(tag_pipe, "BUN")
        self.assertEqual(clean_pipe, "dimebag")

        # Test suffix format
        tag_suf, clean_suf = ClanDetector.extract_clan("Hunk [PRO]")
        self.assertEqual(tag_suf, "PRO")
        self.assertEqual(clean_suf, "Hunk")

        lobby = [
            {"name": "[DR] Hunk", "avg_rating": 5.0},
            {"name": "[DR] Alex", "avg_rating": 4.5},
            {"name": "[DR] Baobab", "avg_rating": 4.8},
            {"name": "SoloPlayer", "avg_rating": 3.0},
        ]
        res = ClanDetector.analyze_clans(lobby)
        self.assertEqual(len(res["clans"]), 1)
        self.assertEqual(res["clans"][0]["tag"], "DR")
        self.assertEqual(res["clans"][0]["count"], 3)
        self.assertEqual(len(res["teaming_warnings"]), 1)

    def test_client_sorted_names_cache(self):
        self.assertTrue(len(self.client._sorted_names_by_length) > 0)
        first_len = len(self.client._sorted_names_by_length[0])
        last_len = len(self.client._sorted_names_by_length[-1])
        self.assertGreaterEqual(first_len, last_len)

    def test_elo_converter_and_win_probability(self):
        from shinri_ranker.analytics import EloConverter
        self.assertEqual(EloConverter.rating_to_elo(1.0), 800)
        self.assertEqual(EloConverter.rating_to_elo(5.0), 2200)
        self.assertEqual(EloConverter.rating_to_elo(3.0), 1500)

        # Equal Elo should yield 50% / 50%
        win_a, win_b = EloConverter.win_probability(1500, 1500)
        self.assertEqual(win_a, 50.0)
        self.assertEqual(win_b, 50.0)

        # Higher Elo should have higher win probability
        win_high, win_low = EloConverter.win_probability(2000, 1600)
        self.assertGreater(win_high, 80.0)
        self.assertLess(win_low, 20.0)

    def test_tournament_generator(self):
        from shinri_ranker.analytics import TournamentGenerator
        players = [
            {"name": f"P{i}", "avg_rating": 5.0 - (i * 0.2)} for i in range(1, 9)
        ]
        # 1. Single Elimination
        bracket = TournamentGenerator.generate_bracket(players, format_type="single_elimination")
        self.assertEqual(bracket["bracket_size"], 8)
        self.assertEqual(len(bracket["matches"]), 4)
        # Seed 1 vs Seed 8
        self.assertEqual(bracket["matches"][0]["seed_1"], 1)
        self.assertEqual(bracket["matches"][0]["seed_2"], 8)

        # 2. Round Robin
        rr = TournamentGenerator.generate_bracket(players, format_type="round_robin")
        self.assertEqual(rr["format"], "round_robin")
        self.assertEqual(rr["groups_count"], 2)
        self.assertIn("Группа A", rr["groups"])
        self.assertIn("Группа B", rr["groups"])
        self.assertEqual(len(rr["groups"]["Группа A"]["players"]), 4)

    def test_sentiment_analyzer(self):
        from shinri_ranker.analytics import SentimentAnalyzer
        good_reviews = [
            {"text": "Отличный игрок, логика и детектив на высшем уровне, скилл супер!", "rating": 5},
            {"text": "Приятно играть, всегда помогает и тащит.", "rating": 5},
        ]
        res_good = SentimentAnalyzer.analyze_reviews(good_reviews)
        self.assertEqual(res_good["sentiment"], "positive")
        self.assertGreater(res_good["polarity"], 0.2)
        self.assertIn("логика", res_good["tags"])

        toxic_reviews = [
            {"text": "Полный токсик, руин матча и лив на втором ходу!", "rating": 1},
            {"text": "Афк тролль, неадекват.", "rating": 1},
        ]
        res_toxic = SentimentAnalyzer.analyze_reviews(toxic_reviews)
        self.assertEqual(res_toxic["sentiment"], "negative")
        self.assertLess(res_toxic["polarity"], -0.2)
        self.assertIn("токсик", res_toxic["tags"])

    def test_player_card_generator(self):
        from shinri_ranker.analytics import PlayerCardGenerator
        legend = {"name": "[PRO] Hunk", "player_id": 3865, "avg_rating": 5.0, "reviews_count": 50}
        card = PlayerCardGenerator.get_player_card(legend)
        self.assertEqual(card["title"], "Абсолютный Детектив")
        self.assertEqual(card["tier"], "S+")
        self.assertEqual(card["clan_tag"], "PRO")
        self.assertEqual(card["clean_name"], "Hunk")
        self.assertEqual(card["elo"], 2200)

        troll = {"name": "Ruiner", "player_id": 9999, "avg_rating": 1.5, "reviews_count": 10}
        card_troll = PlayerCardGenerator.get_player_card(troll)
        self.assertEqual(card_troll["title"], "Главный Подозреваемый")
        self.assertEqual(card_troll["tier"], "D")

    def test_optimized_fuzzy_matcher(self):
        from shinri_ranker.fuzzy import FuzzyMatcher
        matcher = FuzzyMatcher(self.client)
        # Exact match O(1)
        res, ratio = matcher.find_best_match("Hunk")
        self.assertEqual(res["name"], "Hunk")
        self.assertEqual(ratio, 1.0)

        # Typo match with length pruning
        res_typo, ratio_typo = matcher.find_best_match("mercyfllower")
        self.assertEqual(res_typo["name"], "mercyflower^-^")
        self.assertGreaterEqual(ratio_typo, 0.70)


class TestSixteenPlayerMatchEvaluator(unittest.TestCase):
    """Dedicated tests for 16-player match evaluation and two-way sorting."""

    def setUp(self):
        # Create 16 mock player profiles in database
        self.mock_ratings = [
            {"playerId": 100 + i, "playerName": f"Player_{i:02d}", "count": 10 + i * 5, "avg": round(1.0 + (i * 0.25), 2), "last": 1000}
            for i in range(1, 17)
        ]
        self.client = ShinriClient(offline_mode=True)
        self.client._populate_indexes(self.mock_ratings)

    def test_16_players_unified_list_both_sort_directions(self):
        # Create 16 player inputs
        names = [f"Player_{i:02d}" for i in range(1, 17)]
        items = [InputParser.parse_line(name, idx) for idx, name in enumerate(names, 1)]
        self.assertEqual(len(items), 16)

        matcher = ProfileMatcher(self.client)
        results = matcher.process_items(items)
        self.assertEqual(len(results), 16)

        # 1. Best to Worst (Descending)
        report = Ranker.generate_report(results, top_n=16, ranking_mode="bayesian")
        self.assertIsNotNone(report.match_players)
        self.assertEqual(len(report.match_players), 16)

        # Verify all ranks 1..16 are unique and sequential
        ranks_desc = [p.rank for p in report.match_players]
        self.assertEqual(ranks_desc, list(range(1, 17)))

        # Player_16 has the highest score and should be #1 in descending
        self.assertEqual(report.match_players[0].name, "Player_16")
        self.assertEqual(report.match_players[0].rank, 1)
        # Player_01 has the lowest score and should be #16 in descending
        self.assertEqual(report.match_players[-1].name, "Player_01")
        self.assertEqual(report.match_players[-1].rank, 16)

        # 2. Worst to Best (Ascending)
        worst_first = Ranker.sort_match_players(report.match_players, sort_order="asc", ranking_mode="bayesian")
        self.assertEqual(len(worst_first), 16)

        ranks_asc = [p.rank for p in worst_first]
        self.assertEqual(ranks_asc, list(range(1, 17)))

        # Player_01 has the lowest score and should be #1 in ascending (worst-first)
        self.assertEqual(worst_first[0].name, "Player_01")
        self.assertEqual(worst_first[0].rank, 1)
        # Player_16 has the highest score and should be #16 in ascending
        self.assertEqual(worst_first[-1].name, "Player_16")
        self.assertEqual(worst_first[-1].rank, 16)

    def test_16_players_with_unrated_and_missing_profiles(self):
        # 14 rated players + 1 unrated (Alex, 0 reviews) + 1 missing (GhostPlayer)
        mock_data = [
            {"playerId": 200 + i, "playerName": f"Rated_{i:02d}", "count": 20, "avg": round(2.0 + (i * 0.2), 2), "last": 1000}
            for i in range(1, 15)
        ]
        # Alex with 0 reviews
        mock_data.append({"playerId": 999, "playerName": "AlexUnrated", "count": 0, "avg": 0.0, "last": 1000})

        client = ShinriClient(offline_mode=True)
        client._populate_indexes(mock_data)

        # 16 inputs
        input_lines = [f"Rated_{i:02d}" for i in range(1, 15)] + ["AlexUnrated", "GhostPlayerNotFound"]
        self.assertEqual(len(input_lines), 16)

        items = [InputParser.parse_line(l, idx) for idx, l in enumerate(input_lines, 1)]
        matcher = ProfileMatcher(client)
        results = matcher.process_items(items)

        report = Ranker.generate_report(results, top_n=16, ranking_mode="bayesian")
        self.assertEqual(len(report.match_players), 16)

        # Check status metadata
        statuses = [p.status for p in report.match_players]
        self.assertEqual(statuses.count("matched"), 14)
        self.assertEqual(statuses.count("unrated"), 1)
        self.assertEqual(statuses.count("missing"), 1)

        # Verify missing player keeps name and has status "missing"
        missing_player = next(p for p in report.match_players if p.status == "missing")
        self.assertEqual(missing_player.name, "GhostPlayerNotFound")
        self.assertEqual(missing_player.status_label, "Не найден в базе")
        self.assertIsNone(missing_player.bayesian_score)

        # Verify unrated player has status "unrated" and score is None (not fake 0.0)
        unrated_player = next(p for p in report.match_players if p.status == "unrated")
        self.assertEqual(unrated_player.name, "AlexUnrated")
        self.assertEqual(unrated_player.status_label, "Нет оценок")
        self.assertIsNone(unrated_player.bayesian_score)
        self.assertIsNone(unrated_player.avg_rating)

        # Test ascending sort with gaps
        asc_list = Ranker.sort_match_players(report.match_players, sort_order="asc", ranking_mode="bayesian")
        self.assertEqual(len(asc_list), 16)
        # All 16 participants must remain present and numbered 1..16
        self.assertEqual([p.rank for p in asc_list], list(range(1, 17)))

    def test_16_players_comma_separated_single_line(self):
        names = [f"Player_{i:02d}" for i in range(1, 17)]
        comma_text = ", ".join(names)
        items = InputParser.parse_text(comma_text)
        self.assertEqual(len(items), 16)
        parsed_names = [it.extracted_name for it in items]
        self.assertEqual(parsed_names, names)

        matcher = ProfileMatcher(self.client)
        results = matcher.process_items(items)
        self.assertEqual(len(results), 16)
        report = Ranker.generate_report(results, top_n=16, ranking_mode="bayesian")
        self.assertEqual(len(report.match_players), 16)

    def test_16_players_classic_ranking_mode(self):
        names = [f"Player_{i:02d}" for i in range(1, 17)]
        items = [InputParser.parse_line(name, idx) for idx, name in enumerate(names, 1)]
        matcher = ProfileMatcher(self.client)
        results = matcher.process_items(items)

        # Descending (classic)
        report_desc = Ranker.generate_report(results, top_n=16, ranking_mode="classic")
        self.assertEqual(report_desc.match_players[0].name, "Player_16")
        self.assertEqual(report_desc.match_players[-1].name, "Player_01")

        # Ascending (classic)
        asc_list = Ranker.sort_match_players(report_desc.match_players, sort_order="asc", ranking_mode="classic")
        self.assertEqual(asc_list[0].name, "Player_01")
        self.assertEqual(asc_list[-1].name, "Player_16")

    def test_empty_input_validation(self):
        self.assertEqual(len(InputParser.parse_text("")), 0)
        self.assertEqual(len(InputParser.parse_text("   \n\n   ")), 0)
        self.assertEqual(len(InputParser.parse_text("# comment only")), 0)
        self.assertEqual(len(InputParser.parse_text("# comment with, commas, and; semicolons")), 0)
        parsed = InputParser.parse_text("# Note: nick, links, and id\nHunk")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].extracted_name, "Hunk")

    def test_report_dict_has_unified_players(self):
        report = Ranker.generate_report([], top_n=16)
        data = report.to_dict()
        self.assertIn("players", data)
        self.assertIn("match_players", data)
        self.assertEqual(data["summary"]["match_count"], 0)


class TestOcrProcessor(unittest.TestCase):
    def setUp(self):
        from shinri_ranker.ocr import OcrProcessor
        self.ocr = OcrProcessor
        self.client = ShinriClient(offline_mode=True)
        self.client._by_name_lower = {
            "hunk": [{"name": "Hunk", "id": 3865, "avg": 4.88, "count": 97, "avatarGameId": "hunk_1"}],
            "mercyflower^-^": [{"name": "mercyflower^-^", "id": 37725, "avg": 5.0, "count": 62, "avatarGameId": "mercy_1"}],
            "fallenangel": [{"name": "FallenAngel", "id": 36666, "avg": 5.0, "count": 45, "avatarGameId": "angel_1"}],
            "baobabback": [{"name": "BaobabBack", "id": 7292, "avg": 5.0, "count": 44, "avatarGameId": "bao_1"}],
        }
        self.client._is_loaded = True

    def test_clean_ocr_token_patterns(self):
        self.assertEqual(self.ocr.clean_ocr_token("1. Hunk (Host) 5.00"), "Hunk")
        self.assertEqual(self.ocr.clean_ocr_token("#2 mercyflower^-^ 62ms"), "mercyflower^-^")
        self.assertEqual(self.ocr.clean_ocr_token("4) BaobabBack [Dead]"), "BaobabBack")
        self.assertEqual(self.ocr.clean_ocr_token("Игрок 5: FallenAngel ★ 4.95"), "FallenAngel")
        self.assertEqual(self.ocr.clean_ocr_token("16. Bun|dimebag 120 ms"), "Bun|dimebag")
        self.assertEqual(self.ocr.clean_ocr_token("[12:34:56] Hunk: всем привет"), "Hunk")

    def test_process_screenshot_text(self):
        raw_text = """
        1. Hunk (Host) 5.00
        2. mercyflower^-^ 62ms
        3. FallenAnge1 45ms
        4. UnknownPlayer999
        """
        results = self.ocr.process_screenshot_text(raw_text, self.client, auto_fuzzy_correct=True)
        self.assertGreaterEqual(len(results), 3)
        names = [r["matched_name"] for r in results]
        self.assertIn("Hunk", names)
        self.assertIn("mercyflower^-^", names)
        # Verify fuzzy matching corrected FallenAnge1 -> FallenAngel
        self.assertIn("FallenAngel", names)

    def test_clean_clan_tags_and_homoglyphs(self):
        self.assertEqual(self.ocr.clean_ocr_token("еррукар_[ДВП]"), "еррукар")
        self.assertEqual(self.ocr.clean_ocr_token("еррукар-[ДВП1]"), "еррукар")
        self.assertEqual(self.ocr.clean_ocr_token("Player_(PRO)"), "Player")
        self.assertEqual(self.ocr.clean_ocr_token("SIayers"), "Slayers")
        self.assertEqual(self.ocr.clean_ocr_token("sIicemyheart"), "slicemyheart")

    def test_is_danganronpa_character(self):
        self.assertTrue(self.ocr.is_danganronpa_character("Кокичи Ома"))
        self.assertTrue(self.ocr.is_danganronpa_character("Сония Невермайнд"))
        self.assertTrue(self.ocr.is_danganronpa_character("Леон Кувата"))
        self.assertTrue(self.ocr.is_danganronpa_character("Бьякуя Тогами"))
        self.assertTrue(self.ocr.is_danganronpa_character("K1-B0"))
        self.assertTrue(self.ocr.is_danganronpa_character("ю-во"))
        self.assertTrue(self.ocr.is_danganronpa_character("Макото Наэги"))
        self.assertFalse(self.ocr.is_danganronpa_character("dinukio"))
        self.assertFalse(self.ocr.is_danganronpa_character("Slayers"))
        self.assertFalse(self.ocr.is_danganronpa_character("Mood"))

    def test_filter_character_subtitles_in_dro_lobby(self):
        lobby_text = """
        dinukio
        Кокичи Ома
        SIayers
        Бьякуя Тогами
        Mood
        Макото Наэги
        еррукар-[ДВП]
        Кёко Киригири
        Arestik
        ю-во
        """
        results = self.ocr.process_screenshot_text(lobby_text, self.client, auto_fuzzy_correct=True)
        names = [r["matched_name"] for r in results]
        self.assertEqual(names, ["dinukio", "Slayers", "Mood", "еррукар", "Arestik"])

    def test_short_query_fuzzy_protection(self):
        from shinri_ranker.fuzzy import FuzzyMatcher
        mock_client = ShinriClient(offline_mode=True)
        mock_client._ratings = [{"playerId": 43281, "playerName": "Monody"}]
        mock_client._by_name_lower = {"monody": [{"name": "Monody", "id": 43281, "avg": 5.0, "count": 1}]}
        fuzzy = FuzzyMatcher(mock_client)
        # Mood should NOT mutate into Monody despite high character overlap
        res = fuzzy.find_best_match("Mood", cutoff=0.72)
        self.assertIsNone(res)

    def test_clean_player_token(self):
        self.assertEqual(self.ocr.clean_player_token("*eldon"), "Seeldon")
        self.assertEqual(self.ocr.clean_player_token("00wMaus"), "Dowbraus")
        self.assertEqual(self.ocr.clean_player_token("ГИЯ|одуванчик"), "ГИЯ|одуванчик")
        self.assertEqual(self.ocr.clean_player_token("SiderS"), "SiderS")
        self.assertEqual(self.ocr.clean_player_token("Danov"), "Danov")
        self.assertEqual(self.ocr.clean_player_token("38472"), "38472")

    def test_extract_cards_grid_geometry(self):
        from PIL import Image
        # A square image or portrait image is not a DRO card strip/grid
        img_square = Image.new("RGB", (200, 200), color="black")
        res_square = self.ocr.extract_cards_grid(img_square, self.client)
        self.assertEqual(res_square, [])

        img_tall = Image.new("RGB", (200, 800), color="black")
        res_tall = self.ocr.extract_cards_grid(img_tall, self.client)
        self.assertEqual(res_tall, [])

    def test_extract_cards_grid_16_players(self):
        import os
        from PIL import Image
        img_path = r"C:\Users\mdeni\.gemini\antigravity\brain\5fa64bc0-0719-4068-97dd-a42e136360fa\.user_uploaded\media_1790934713010.png"
        if not os.path.exists(img_path):
            self.skipTest("Screenshot media_1790934713010.png not found")
        real_client = ShinriClient()
        real_client.load_ratings()
        img = Image.open(img_path)
        _, candidates = self.ocr.process_image(img, real_client)
        self.assertEqual(len(candidates), 16)
        names = [c["matched_name"] for c in candidates]
        self.assertIn("Seeldon", names)
        self.assertIn("Шрёдингер", names)
        self.assertIn("StiveTreik", names)
        self.assertIn("38472", names)
        self.assertIn("papagetto_", names)
        self.assertIn("Dowbraus", names)
        self.assertIn("SiderS", names)
        self.assertIn("Gorsh0k", names)
        self.assertIn("Danov", names)
        self.assertIn("ябитнулгриф", names)


    def test_binary_marshal_cache(self):
        temp_dir = tempfile.mkdtemp()
        json_path = os.path.join(temp_dir, "test_cache.json")
        data = {
            "timestamp": 123456789,
            "ratings": [{"playerId": 1, "playerName": "TestPlayer", "count": 5, "avg": 4.5}]
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        test_client = ShinriClient(cache_path=json_path, offline_mode=True)
        read_data = test_client._read_cache_file()
        self.assertIsNotNone(read_data)
        self.assertEqual(len(read_data["ratings"]), 1)
        # Check that .dat file was automatically created
        self.assertTrue(os.path.exists(json_path + ".dat"))

        # Re-reading should successfully load from .dat file
        second_read = test_client._read_cache_file()
        self.assertEqual(second_read["ratings"][0]["playerName"], "TestPlayer")


if __name__ == "__main__":
    unittest.main()


