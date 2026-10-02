"""Presentation changes preserve numeric ratings, ranks and severity meaning."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console
from shinri_ranker.cli import print_plain_lobby_safety, print_rich_lobby_safety, print_rich_report
from shinri_ranker.client import ShinriClient
from shinri_ranker.matcher import InputParser, ProfileMatcher
from shinri_ranker.ranker import Ranker
from shinri_ranker.exporter import Exporter


class TestInterfaceText(unittest.TestCase):
    def test_safety_levels_have_words_in_rich_output(self):
        output = io.StringIO()
        safety = {
            "score": 60,
            "label": "Проверка",
            "warnings": [
                {"severity": severity, "text": "Тест"} for severity in ["danger", "warning", "info"]
            ],
        }
        print_rich_lobby_safety(safety, Console(file=output, width=120, color_system=None))
        for label in ["Опасность", "Предупреждение", "Информация"]:
            self.assertIn(label, output.getvalue())

    def test_plain_safety_retains_severity_and_score(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_plain_lobby_safety(
                {
                    "score": 42,
                    "label": "Проверка",
                    "warnings": [{"severity": "danger", "text": "Риск"}],
                }
            )
        self.assertIn("42/100", output.getvalue())
        self.assertIn("[ОПАСНОСТЬ]", output.getvalue())

    def test_rank_and_rating_survive_rich_report(self):
        with TemporaryDirectory() as directory:
            client = ShinriClient(cache_path=str(Path(directory) / "cache.json"), offline_mode=True)
            client._populate_indexes(
                [
                    {"playerId": i, "playerName": f"Player{i}", "avg": 4.25, "count": 10}
                    for i in range(1, 4)
                ]
            )
            report = Ranker.generate_report(
                ProfileMatcher(client).process_items(
                    InputParser.parse_text("#1\n#2\n#3"), allow_online=False
                ),
                top_n=3,
            )
            output = io.StringIO()
            print_rich_report(report, Console(file=output, width=160, color_system=None))
            for label in ["Player1", "Player2", "Player3", "4.25"]:
                self.assertIn(label, output.getvalue())
            markdown = Exporter.to_markdown(report)
            self.assertIn("| **1** | Player1 | **4.25**", markdown)
            self.assertNotIn("★", markdown)
            self.assertNotIn("★", output.getvalue())
