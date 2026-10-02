"""
Embedded HTTP Web Server and REST API for Shinri Reviews Ranker.
Includes support for Bayesian ranking, character avatars, chat log parsing,
detailed review inspection, and head-to-head comparison.
"""

from __future__ import annotations
import gzip
import hashlib
import json
import logging
import mimetypes
import os
import sys
import socketserver
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from .client import ShinriClient, ShinriNetworkError
from .exporter import Exporter
from .matcher import InputParser, ProfileMatcher, ChatLogExtractor
from .ranker import Ranker
from .analytics import (
    TeamBalancer,
    LobbySafetyMeter,
    ReviewRingDetector,
    TournamentGenerator,
    ClanDetector,
    PlayerCardGenerator,
    SentimentAnalyzer,
    EloConverter,
)
from .ocr import OcrProcessor

logger = logging.getLogger("shinri_server")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class ShinriRequestHandler(BaseHTTPRequestHandler):
    client: ShinriClient
    static_dir: str
    _STATIC_CACHE: Dict[str, Dict[str, Any]] = {}

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status=status)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path == "/api/status":
            self.handle_api_status()
        elif path == "/api/export-cache":
            self.handle_api_export_cache()
        elif path == "/api/player-details":
            self.handle_api_player_details(query)
        elif path == "/api/player-card":
            self.handle_api_player_card(query)
        elif path == "/" or path == "/index.html":
            self.serve_file(os.path.join(self.static_dir, "index.html"), "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            full_path = os.path.join(self.static_dir, rel_path)
            self.serve_file(full_path)
        else:
            candidate = os.path.join(self.static_dir, path.lstrip("/"))
            if os.path.isfile(candidate):
                self.serve_file(candidate)
            else:
                self.serve_file(os.path.join(self.static_dir, "index.html"), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            req_json = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            self._send_error("Некорректный JSON в теле запроса", 400)
            return

        if path == "/api/rank":
            self.handle_api_rank(req_json)
        elif path == "/api/parse-log":
            self.handle_api_parse_log(req_json)
        elif path == "/api/balance-teams":
            self.handle_api_balance_teams(req_json)
        elif path == "/api/tournament-bracket":
            self.handle_api_tournament_bracket(req_json)
        elif path == "/api/clans":
            self.handle_api_clans(req_json)
        elif path == "/api/player-card":
            self.handle_api_player_card_post(req_json)
        elif path == "/api/lobby-safety":
            self.handle_api_lobby_safety(req_json)
        elif path == "/api/ocr-process":
            self.handle_api_ocr_process(req_json)
        elif path == "/api/compare":
            self.handle_api_compare(req_json)
        elif path == "/api/refresh":
            self.handle_api_refresh()
        elif path == "/api/import-cache":
            self.handle_api_import_cache(req_json)
        else:
            self._send_error("Эндпоинт не найден", 404)

    def handle_api_status(self) -> None:
        try:
            if not self.client.is_loaded:
                self.client.load_ratings()
            self._send_json({
                "status": "ok",
                "loaded": self.client.is_loaded,
                "total_players": self.client.total_rated_players,
                "data_source": self.client.data_source,
                "global_avg": self.client.global_avg_rating,
                "offline_mode": self.client.offline_mode,
            })
        except Exception as e:
            self._send_json({
                "status": "error",
                "error": str(e),
                "loaded": False,
                "total_players": 0,
                "data_source": "error",
                "global_avg": 4.80,
                "offline_mode": self.client.offline_mode,
            })

    def handle_api_refresh(self) -> None:
        try:
            delta = self.client.refresh_delta()
            self._send_json({
                "status": "ok",
                "total_players": self.client.total_rated_players,
                "global_avg": self.client.global_avg_rating,
                "data_source": self.client.data_source,
                "delta": delta,
            })
        except Exception as e:
            self._send_error(f"Не удалось обновить базу: {e}", 500)

    def handle_api_import_cache(self, req_json: Dict[str, Any]) -> None:
        raw_data = req_json.get("data")
        if not raw_data:
            self._send_error("Отсутствуют данные для импорта", 400)
            return

        try:
            parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            ratings = parsed.get("ratings") if isinstance(parsed, dict) else parsed
            if not isinstance(ratings, list):
                self._send_error("Формат базы должен быть списком игроков или объектом с 'ratings'", 400)
                return

            self.client._populate_indexes(ratings)
            self.client._loaded_at = 0
            self.client._data_source = "manual_import"
            self.client._write_cache_file(ratings)

            self._send_json({
                "status": "ok",
                "imported_count": len(ratings),
            })
        except Exception as e:
            self._send_error(f"Ошибка при импорте базы: {e}", 500)

    def handle_api_export_cache(self) -> None:
        try:
            if not self.client.is_loaded:
                self.client.load_ratings()
            data = {
                "count": self.client.total_rated_players,
                "ratings": self.client._ratings,
            }
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=\"shinri_database.json\"")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._send_error(f"Ошибка экспорта базы: {e}", 500)

    def handle_api_player_details(self, query: Dict[str, List[str]]) -> None:
        raw_id = query.get("id", [None])[0]
        if not raw_id:
            self._send_error("Параметр 'id' обязателен", 400)
            return

        try:
            pid = int(raw_id)
        except ValueError:
            self._send_error("Некорректный ID", 400)
            return

        # Fetch base info + deep reviews
        base_info = self.client.find_by_id(pid) or self.client.fetch_player_online_by_id(pid)
        if not base_info:
            self._send_error(f"Игрок с ID {pid} не найден", 404)
            return

        details = self.client.fetch_player_detailed_reviews(pid)
        nick_history = self.client.fetch_player_nick_history(pid)
        card = PlayerCardGenerator.get_player_card(base_info)

        resp = {
            "player": base_info,
            "details": details,
            "nick_history": nick_history,
            "card": card,
        }
        self._send_json(resp)

    def handle_api_player_card(self, query: Dict[str, List[str]]) -> None:
        raw_id = query.get("id", [None])[0]
        if not raw_id:
            self._send_error("Параметр 'id' обязателен", 400)
            return
        try:
            pid = int(raw_id)
        except ValueError:
            self._send_error("Некорректный ID", 400)
            return

        base = self.client.find_by_id(pid) or self.client.fetch_player_online_by_id(pid)
        if not base:
            self._send_error(f"Игрок с ID {pid} не найден", 404)
            return

        card = PlayerCardGenerator.get_player_card(base)
        self._send_json(card)

    def handle_api_player_card_post(self, req_json: Dict[str, Any]) -> None:
        player = req_json.get("player")
        if not player:
            self._send_error("Передайте данные игрока в поле 'player'", 400)
            return
        card = PlayerCardGenerator.get_player_card(player)
        self._send_json(card)

    def handle_api_tournament_bracket(self, req_json: Dict[str, Any]) -> None:
        players = req_json.get("players", [])
        fmt = req_json.get("format", "single_elimination")
        metric = req_json.get("metric", "bayesian_score")
        if not players:
            self._send_error("Передайте список игроков для турнирной сетки", 400)
            return
        res = TournamentGenerator.generate_bracket(players, format_type=fmt, metric=metric)
        self._send_json(res)

    def handle_api_clans(self, req_json: Dict[str, Any]) -> None:
        players = req_json.get("players", [])
        if not players:
            self._send_error("Передайте список игроков для анализа кланов", 400)
            return
        res = ClanDetector.analyze_clans(players)
        self._send_json(res)

    def handle_api_parse_log(self, req_json: Dict[str, Any]) -> None:
        log_text = req_json.get("text", "")
        extracted = ChatLogExtractor.extract_from_log(log_text)
        self._send_json({
            "players": extracted,
            "count": len(extracted),
        })

    def handle_api_compare(self, req_json: Dict[str, Any]) -> None:
        player_ids = req_json.get("ids", [])
        if not player_ids or not isinstance(player_ids, list):
            self._send_error("Передайте список ID игроков в поле 'ids'", 400)
            return

        results = []
        for raw_id in player_ids[:4]:  # compare up to 4 players
            try:
                pid = int(raw_id)
            except ValueError:
                continue

            base = self.client.find_by_id(pid) or self.client.fetch_player_online_by_id(pid)
            if base:
                details = self.client.fetch_player_detailed_reviews(pid)
                nick_history = self.client.fetch_player_nick_history(pid)
                bayes = Ranker.calculate_bayesian_score(base["avg"], base["count"], self.client.global_avg_rating)
                results.append({
                    "id": pid,
                    "name": base["name"],
                    "avg": base["avg"],
                    "bayesian_score": round(bayes, 2),
                    "count": base["count"],
                    "avatar_url": base.get("avatar_url"),
                    "profile_url": base["profile_url"],
                    "verified_avg": details.get("verified_avg"),
                    "verified_count": details.get("verified_count", 0),
                    "top_review": details.get("top_review"),
                    "tags": details.get("tags", []),
                    "nick_history": nick_history.get("history", []),
                })

        self._send_json({"players": results})

    def handle_api_balance_teams(self, req_json: Dict[str, Any]) -> None:
        metric = req_json.get("metric", "bayesian_score")
        if "team_a" in req_json and "team_b" in req_json:
            res = TeamBalancer.calculate_roster_stats(
                req_json.get("team_a", []),
                req_json.get("team_b", []),
                metric=metric,
            )
            self._send_json(res)
            return

        players = req_json.get("players", [])
        if not players:
            self._send_error("Передайте список игроков для балансировки", 400)
            return

        res = TeamBalancer.balance_teams(players, metric=metric)
        self._send_json(res)

    def handle_api_lobby_safety(self, req_json: Dict[str, Any]) -> None:
        ranked = req_json.get("best_players", []) + req_json.get("worst_players", [])
        unrated = req_json.get("unrated_players", [])
        res = LobbySafetyMeter.analyze_lobby(ranked, unrated)
        self._send_json(res)

    def handle_api_ocr_process(self, req_json: Dict[str, Any]) -> None:
        raw_image = req_json.get("image")
        raw_text = req_json.get("text", "")

        if raw_image:
            recognized_text, candidates = OcrProcessor.process_image(raw_image, self.client, auto_fuzzy_correct=True)
            clean_text = "\n".join(c["matched_name"] for c in candidates)
            self._send_json({
                "recognized_text": clean_text,
                "clean_text": clean_text,
                "raw_ocr": recognized_text,
                "candidates": candidates,
                "engine": "windows_native" if candidates else "fallback",
            })
            return

        if not raw_text.strip():
            self._send_error("Передайте изображение (image) или текст (text) для распознавания", 400)
            return

        candidates = OcrProcessor.process_screenshot_text(raw_text, self.client, auto_fuzzy_correct=True)
        clean_text = "\n".join(c["matched_name"] for c in candidates)
        self._send_json({
            "recognized_text": clean_text,
            "clean_text": clean_text,
            "raw_ocr": raw_text,
            "candidates": candidates,
            "engine": "text_parsing",
        })

    def handle_api_rank(self, req_json: Dict[str, Any]) -> None:
        raw_input = req_json.get("text", "")
        top_n = int(req_json.get("top_n", 16))
        min_reviews = int(req_json.get("min_reviews", 1))
        strategy = req_json.get("ambiguous_strategy", "most_reviews")
        ranking_mode = req_json.get("ranking_mode", "bayesian")
        m_confidence = int(req_json.get("m_confidence", 5))
        is_chat_log = bool(req_json.get("is_chat_log", False))
        sort_order = req_json.get("sort_order", "desc")
        is_live = bool(req_json.get("is_live", False))
        include_export = bool(req_json.get("include_export", False))

        if not raw_input or not raw_input.strip():
            self._send_error("Список участников пуст. Пожалуйста, введите никнеймы игроков для матча (16 участников).", 400)
            return

        try:
            if not self.client.is_loaded:
                self.client.load_ratings()
        except ShinriNetworkError as e:
            self._send_error(f"Ошибка доступа к данным: {e}", 503)
            return
        except Exception as e:
            self._send_error(f"Ошибка инициализации базы данных: {e}", 500)
            return

        # Parse inputs
        items = InputParser.parse_text(raw_input, is_chat_log=is_chat_log)
        if not items:
            self._send_error("Не удалось распознать ни одного игрока во входном тексте. Введите имена или ссылки по одной на строку.", 400)
            return

        # Match profiles (skip slow online network requests if typing in live eval mode)
        matcher = ProfileMatcher(self.client)
        matched_results = matcher.process_items(
            items,
            resolve_ambiguous_strategy=strategy,
            allow_online=not is_live,
        )

        # Rank
        report = Ranker.generate_report(
            matched_results,
            top_n=top_n,
            min_reviews=min_reviews,
            ranking_mode=ranking_mode,
            global_avg=self.client.global_avg_rating,
            m_confidence=m_confidence,
        )

        # Apply sort order to match_players if ascending requested
        if sort_order == "asc" and report.match_players:
            report.match_players = Ranker.sort_match_players(
                report.match_players,
                sort_order="asc",
                ranking_mode=ranking_mode,
            )

        resp_data = report.to_dict()
        if include_export:
            resp_data["markdown"] = Exporter.to_markdown(report)
            resp_data["csv"] = Exporter.to_csv(report)
        else:
            resp_data["markdown"] = ""
            resp_data["csv"] = ""
        resp_data["participant_count"] = len(report.match_players or [])
        resp_data["is_16_match"] = len(report.match_players or []) == 16
        resp_data["sort_order"] = sort_order

        if len(report.match_players or []) != 16:
            count = len(report.match_players or [])
            resp_data["validation_warning"] = (
                f"Введено {count} из 16 участников матча."
            )

        self._send_json(resp_data)

    @classmethod
    def preload_static_cache(cls, static_dir: str) -> None:
        """Pre-warm memory cache for all static files to achieve zero-disk-I/O serving."""
        if not static_dir or not os.path.isdir(static_dir):
            return
        for root, _, files in os.walk(static_dir):
            for file in files:
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, "rb") as f:
                        content = f.read()
                    mtime = os.path.getmtime(full_path)
                    if full_path.endswith(".ico"):
                        resolved_content_type = "image/x-icon"
                    elif full_path.endswith(".svg"):
                        resolved_content_type = "image/svg+xml"
                    else:
                        mime, _ = mimetypes.guess_type(full_path)
                        resolved_content_type = (
                            f"{mime}; charset=utf-8" if mime and "text" in mime else (mime or "application/octet-stream")
                        )
                    etag = f'"{hashlib.md5(content).hexdigest()}"'
                    is_compressible = any(t in (resolved_content_type or "") for t in ["text", "javascript", "json", "html", "css"])
                    gzip_content = gzip.compress(content, compresslevel=6) if is_compressible and len(content) > 256 else None
                    cls._STATIC_CACHE[full_path] = {
                        "mtime": mtime,
                        "content": content,
                        "content_type": resolved_content_type,
                        "etag": etag,
                        "gzip_content": gzip_content,
                    }
                except Exception:
                    pass

    def serve_file(self, full_path: str, content_type: Optional[str] = None) -> None:
        # Fast RAM hit: if already cached and frozen, skip all disk checks
        is_frozen = getattr(sys, "frozen", False)
        cache_entry = self._STATIC_CACHE.get(full_path)

        if cache_entry is None or not is_frozen:
            if not os.path.isfile(full_path):
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"404 Not Found")
                return

            try:
                mtime = os.path.getmtime(full_path)
                if not cache_entry or cache_entry.get("mtime") != mtime:
                    resolved_content_type = content_type
                    if not resolved_content_type:
                        if full_path.endswith(".ico"):
                            resolved_content_type = "image/x-icon"
                        elif full_path.endswith(".svg"):
                            resolved_content_type = "image/svg+xml"
                        else:
                            mime, _ = mimetypes.guess_type(full_path)
                            resolved_content_type = (
                                f"{mime}; charset=utf-8" if mime and "text" in mime else (mime or "application/octet-stream")
                            )

                    with open(full_path, "rb") as f:
                        content = f.read()

                    etag = f'"{hashlib.md5(content).hexdigest()}"'
                    is_compressible = any(t in (resolved_content_type or "") for t in ["text", "javascript", "json", "html", "css"])
                    gzip_content = gzip.compress(content, compresslevel=6) if is_compressible and len(content) > 256 else None

                    cache_entry = {
                        "mtime": mtime,
                        "content": content,
                        "content_type": resolved_content_type,
                        "etag": etag,
                        "gzip_content": gzip_content,
                    }
                    self._STATIC_CACHE[full_path] = cache_entry
            except Exception as e:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                return

        # Static assets can be cached aggressively in client WebView2
        is_html = full_path.endswith(".html") or full_path.endswith(".htm")
        cache_header = "no-cache" if is_html else "public, max-age=31536000, immutable"

        # ETag 304 validation
        if_none_match = self.headers.get("If-None-Match")
        if if_none_match and if_none_match.strip() == cache_entry["etag"]:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", cache_entry["etag"])
            self.send_header("Cache-Control", cache_header)
            self.end_headers()
            return

        accept_encoding = self.headers.get("Accept-Encoding", "")
        can_gzip = "gzip" in accept_encoding and cache_entry["gzip_content"] is not None

        body = cache_entry["gzip_content"] if can_gzip else cache_entry["content"]

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", cache_entry["content_type"])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", cache_entry["etag"])
        self.send_header("Cache-Control", cache_header)
        if can_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8088,
    client: Optional[ShinriClient] = None,
    static_dir: Optional[str] = None,
) -> ThreadingHTTPServer:
    if client is None:
        client = ShinriClient()

    if static_dir is None:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            cand1 = os.path.join(sys._MEIPASS, "shinri_ranker", "static")
            cand2 = os.path.join(sys._MEIPASS, "static")
            static_dir = cand1 if os.path.isdir(cand1) else (cand2 if os.path.isdir(cand2) else None)
        if not static_dir or not os.path.isdir(static_dir):
            static_dir = os.path.join(os.path.dirname(__file__), "static")

    class BoundHandler(ShinriRequestHandler):
        pass

    BoundHandler.client = client
    BoundHandler.static_dir = static_dir

    # Preload all static assets into RAM cache immediately
    if static_dir:
        BoundHandler.preload_static_cache(static_dir)

    actual_port = port
    for offset in range(10):
        try:
            return ThreadingHTTPServer((host, actual_port), BoundHandler)
        except OSError:
            actual_port += 1

    raise RuntimeError(f"Не удалось привязать сервер к {host}:{port}-{port+10}")
