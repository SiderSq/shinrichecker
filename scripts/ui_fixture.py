"""Deterministic offline server for browser regressions; never fetches live profiles."""

import json
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shinri_ranker.client import ShinriClient
from shinri_ranker.server import create_server

NAMES = [
    "Hunk",
    "mercyflower^-^",
    "FallenAngel",
    "BaobabBack",
    "LaFilozofo",
    "blossoms.",
    "TheRedEyes",
    "DIZEY",
    "fantikkss",
    "Zeranix",
    "cucumber",
    "Bun|dimebag",
    "Pateti",
    "Alex",
    "Seeldon",
    "SiderS",
]


def main():
    with tempfile.TemporaryDirectory() as directory:
        client = ShinriClient(cache_path=str(Path(directory) / "cache.json"), offline_mode=True)
        client._populate_indexes(
            [
                {
                    "playerId": i,
                    "playerName": name,
                    "avg": round(4.9 - i * 0.08, 2),
                    "count": 12 + i,
                }
                for i, name in enumerate(NAMES, 1)
            ]
        )
        server = create_server(port=0, client=client)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        print(url, flush=True)
        signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
