"""
Input parsing, profile matching, duplicate detection, ambiguity resolution,
and chat/lobby log extraction.
"""

from __future__ import annotations
import concurrent.futures
import csv
import io
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import logging
import time
from .client import ShinriClient, ShinriNetworkError

logger = logging.getLogger(__name__)


class MatchStatus(str, Enum):
    MATCHED = "matched"  # Successfully matched with rating
    UNRATED = "unrated"  # Profile exists, but 0 reviews / rating unavailable
    AMBIGUOUS = "ambiguous"  # Multiple profiles match the name
    MISSING = "missing"  # Profile not found on site
    DUPLICATE = "duplicate"  # Duplicate entry in input


@dataclass
class PlayerResult:
    input_text: str
    line_number: int
    status: MatchStatus
    player_id: Optional[int] = None
    name: Optional[str] = None
    avg_rating: Optional[float] = None
    reviews_count: Optional[int] = None
    avatar_url: Optional[str] = None
    profile_url: Optional[str] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    resolution_note: Optional[str] = None
    duplicate_of_id: Optional[int] = None
    duplicate_of_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_text": self.input_text,
            "line_number": self.line_number,
            "status": self.status.value,
            "player_id": self.player_id,
            "name": self.name,
            "avg_rating": self.avg_rating,
            "reviews_count": self.reviews_count,
            "avatar_url": self.avatar_url,
            "profile_url": self.profile_url,
            "candidates": self.candidates,
            "resolution_note": self.resolution_note,
            "duplicate_of_id": self.duplicate_of_id,
            "duplicate_of_name": self.duplicate_of_name,
        }


@dataclass
class ParseItem:
    raw_text: str
    line_number: int
    extracted_id: Optional[int] = None
    extracted_name: Optional[str] = None


class ChatLogExtractor:
    """
    Intelligent extractor for Danganronpa Online (DRO) logs, chat transcripts,
    and unstructured lobby player lists.
    """

    # Stopwords to filter out system messages and generic tokens
    STOP_WORDS = {
        "система",
        "сервер",
        "server",
        "system",
        "комната",
        "room",
        "лобби",
        "lobby",
        "хост",
        "host",
        "игра",
        "game",
        "старт",
        "start",
        "триал",
        "trial",
        "чат",
        "chat",
        "участники",
        "игроки",
        "players",
        "members",
        "админ",
        "admin",
        "бот",
        "bot",
    }

    # Precompiled regex patterns for speed
    RE_LOBBY_HEADER = re.compile(
        r"(?:комната|лобби|игроки|players|room|members)(?:\s*#[a-zA-Z0-9_\-]+)?(?:\s*\([^)]*\))?:\s*(.+)$",
        re.IGNORECASE,
    )
    RE_JOIN_MSG = re.compile(
        r"(?:\[[\d:]+\]\s*)?([a-zA-Zа-яА-Я0-9_\-^`|.]+?)\s+(?:вошел|вошла|подключился|подключилась|joined|entered)(?:\s+в\s+комнату|\s+the\s+room)?",
        re.IGNORECASE,
    )
    RE_CHAT_MSG = re.compile(r"^(?:\[[\d:]+\]\s*)?([a-zA-Zа-яА-Я0-9_\-^`|.]+?)\s*:\s*.+$")
    RE_NAME_DELIMITERS = re.compile(r"[,;\t]|\s+[|/]\s+")

    @classmethod
    def extract_from_log(cls, text: str) -> List[str]:
        found_players: List[str] = []
        seen = set()

        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue

            # Pattern 1: Lobby player list header: "Комната: P1, P2, P3" or "Игроки: P1, P2"
            lobby_match = cls.RE_LOBBY_HEADER.search(clean)
            if lobby_match:
                names = [
                    n.strip()
                    for n in cls.RE_NAME_DELIMITERS.split(lobby_match.group(1))
                    if n.strip()
                ]
                for name in names:
                    if name.lower() not in cls.STOP_WORDS and name.lower() not in seen:
                        seen.add(name.lower())
                        found_players.append(name)
                continue

            # Pattern 2: Join / Leave messages: "[18:30] PlayerName вошел в комнату"
            join_match = cls.RE_JOIN_MSG.search(clean)
            if join_match:
                name = join_match.group(1).strip()
                if name.lower() not in cls.STOP_WORDS and name.lower() not in seen:
                    seen.add(name.lower())
                    found_players.append(name)
                continue

            # Pattern 3: Chat sender: "[12:34:56] PlayerName: text"
            chat_match = cls.RE_CHAT_MSG.match(clean)
            if chat_match:
                name = chat_match.group(1).strip()
                if name.lower() not in cls.STOP_WORDS and name.lower() not in seen:
                    seen.add(name.lower())
                    found_players.append(name)
                continue

        return found_players


class InputParser:
    """Parses various raw text formats, links, IDs, chat logs, and CSV files."""

    URL_ID_PATTERNS = [
        re.compile(r"https?://(?:www\.)?shinrireviews\.com/(?:#/)?p/(\d+)", re.IGNORECASE),
        re.compile(r"shinrireviews\.com/(?:#/)?p/(\d+)", re.IGNORECASE),
        re.compile(r"(?:^|/|\s)p/(\d+)(?:/|$|\s)", re.IGNORECASE),
        re.compile(r"https?://(?:www\.)?shinrireviews\.com/(?:#/)?players/(\d+)", re.IGNORECASE),
    ]

    NUMERIC_ID_PATTERN = re.compile(r"^#?(\d+)$")

    @classmethod
    def parse_line(cls, line: str, line_num: int = 1) -> Optional[ParseItem]:
        cleaned = line.strip().strip("\ufeff\"' ")
        if not cleaned:
            return None

        # Check numeric ID with hash, e.g. #3865
        hash_id_match = re.match(r"^#\s*(\d+)$", cleaned)
        if hash_id_match:
            pid = int(hash_id_match.group(1))
            return ParseItem(raw_text=cleaned, line_number=line_num, extracted_id=pid)

        # Skip comment lines
        if cleaned.startswith(("#", "//")):
            return None

        # 1. Try URL patterns
        for pattern in cls.URL_ID_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                pid = int(match.group(1))
                return ParseItem(raw_text=cleaned, line_number=line_num, extracted_id=pid)

        # 2. Try pure numeric ID (#3865 or 3865)
        num_match = cls.NUMERIC_ID_PATTERN.match(cleaned)
        if num_match:
            pid = int(num_match.group(1))
            return ParseItem(raw_text=cleaned, line_number=line_num, extracted_id=pid)

        # 3. Otherwise treat as player name/nickname
        return ParseItem(raw_text=cleaned, line_number=line_num, extracted_name=cleaned)

    @classmethod
    def parse_text(cls, text: str, is_chat_log: bool = False) -> List[ParseItem]:
        if is_chat_log:
            extracted_names = ChatLogExtractor.extract_from_log(text)
            return [
                ParseItem(raw_text=name, line_number=idx, extracted_name=name)
                for idx, name in enumerate(extracted_names, start=1)
            ]

        # Automatic detection: check if text looks like a game/chat log
        if any(
            kw in text.lower()
            for kw in [
                "вошел в комнату",
                "вошла в комнату",
                "joined the room",
                "комната #",
                "лобби #",
            ]
        ):
            extracted = ChatLogExtractor.extract_from_log(text)
            if extracted:
                return [
                    ParseItem(raw_text=name, line_number=idx, extracted_name=name)
                    for idx, name in enumerate(extracted, start=1)
                ]

        items: List[ParseItem] = []
        lines = text.splitlines()

        # Check if CSV-like content
        if any("," in l or ";" in l or "\t" in l for l in lines[:10]):
            parsed_csv = cls._try_parse_csv(text)
            if parsed_csv:
                return parsed_csv

        from .ocr import OcrProcessor, DE_HOMOGLYPH_MAP

        for idx, line in enumerate(lines, start=1):
            cl = line.strip()
            if (
                not cl
                or cl.startswith("//")
                or (cl.startswith("#") and not re.fullmatch(r"#\s*\d+", cl))
            ):
                continue
            if OcrProcessor.is_danganronpa_character(cl):
                continue
            clean_alnum = re.sub(r"[^\w]", "", cl.lower())
            if clean_alnum in DE_HOMOGLYPH_MAP:
                line = DE_HOMOGLYPH_MAP[clean_alnum]

            item = cls.parse_line(line, idx)
            if item:
                items.append(item)

        return items

    @classmethod
    def _try_parse_csv(cls, text: str) -> Optional[List[ParseItem]]:
        valid_lines = [
            l
            for l in text.splitlines()
            if l.strip()
            and not l.strip().startswith("//")
            and (not l.strip().startswith("#") or re.match(r"#\s*\d+(?:[,;\t]|$)", l.strip()))
        ]
        if not valid_lines:
            return None
        clean_text = "\n".join(valid_lines)
        sample = "\n".join(valid_lines[:5])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = "," if any("," in l for l in valid_lines) else ";"

        reader = csv.reader(io.StringIO(clean_text), delimiter=delimiter)
        items: List[ParseItem] = []
        header_skipped = False
        item_counter = 1

        for row in reader:
            if not row:
                continue
            cells = [c.strip().strip("\"' ") for c in row if c.strip()]
            if not cells:
                continue

            if not header_skipped:
                header_words = {
                    "name",
                    "player",
                    "имя",
                    "игрок",
                    "ник",
                    "nick",
                    "nickname",
                    "url",
                    "link",
                    "ссылка",
                    "id",
                }
                if any(c.lower() in header_words for c in cells):
                    header_skipped = True
                    continue

            # If this is a structured table with header, each row represents one player
            if header_skipped:
                chosen_cell = None
                for cell in cells:
                    if any(
                        p.search(cell) for p in cls.URL_ID_PATTERNS
                    ) or cls.NUMERIC_ID_PATTERN.match(cell):
                        chosen_cell = cell
                        break
                if not chosen_cell:
                    chosen_cell = cells[0]
                item = cls.parse_line(chosen_cell, item_counter)
                if item:
                    items.append(item)
                    item_counter += 1
            else:
                # If row has exactly 2 cells and one is a URL/ID while the other is a name, treat as 1 player
                has_url_or_id = any(
                    any(p.search(c) for p in cls.URL_ID_PATTERNS) or cls.NUMERIC_ID_PATTERN.match(c)
                    for c in cells
                )
                if len(cells) == 2 and has_url_or_id:
                    chosen_cell = (
                        cells[1]
                        if (
                            any(p.search(cells[1]) for p in cls.URL_ID_PATTERNS)
                            or cls.NUMERIC_ID_PATTERN.match(cells[1])
                        )
                        else cells[0]
                    )
                    item = cls.parse_line(chosen_cell, item_counter)
                    if item:
                        items.append(item)
                        item_counter += 1
                else:
                    # Delimiter-separated list of multiple players on the same line
                    for cell in cells:
                        item = cls.parse_line(cell, item_counter)
                        if item:
                            items.append(item)
                            item_counter += 1

        return items if items else None


class ProfileMatcher:
    """Matches parsed input items against Shinri Reviews data."""

    def __init__(self, client: ShinriClient):
        self.client = client
        from .fuzzy import FuzzyMatcher

        self.fuzzy = FuzzyMatcher(client)
        self._lookup_errors = set()

    def process_items(
        self,
        items: List[ParseItem],
        resolve_ambiguous_strategy: str = "most_reviews",
        allow_online: bool = True,
    ) -> List[PlayerResult]:
        # Fast concurrent pre-fetch for unresolved players when online lookups are allowed
        if allow_online and not self.client.offline_mode:
            unresolved_names: Set[str] = set()
            unresolved_ids: Set[int] = set()
            for item in items:
                if item.extracted_id is not None:
                    pid = item.extracted_id
                    if not self.client.find_by_id(pid):
                        if pid not in getattr(
                            self.client, "_online_id_cache", {}
                        ) and pid not in getattr(self.client, "_negative_id_cache", set()):
                            unresolved_ids.add(pid)
                else:
                    name = (item.extracted_name or item.raw_text).strip()
                    if not self.client.find_by_name(name):
                        has_clan = False
                        try:
                            from .analytics import ClanDetector

                            clan_tag, clean_name = ClanDetector.extract_clan(name)
                            if clan_tag and clean_name and self.client.find_by_name(clean_name):
                                has_clan = True
                        except Exception:
                            pass
                        if not has_clan:
                            name_lower = name.lower()
                            if name_lower not in getattr(
                                self.client, "_online_name_cache", {}
                            ) and name_lower not in getattr(
                                self.client, "_negative_name_cache", set()
                            ):
                                unresolved_names.add(name)

            if unresolved_names or unresolved_ids:
                max_w = min(8, len(unresolved_names) + len(unresolved_ids))
                deadline = time.monotonic() + 8.0
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_w)

                def lookup(kind, value):
                    with self.client.lookup_deadline(deadline):
                        if kind == "name":
                            return self.client.fetch_player_online_by_name(value)
                        return self.client.fetch_player_online_by_id(value)

                jobs = {executor.submit(lookup, "name", n): n.lower() for n in unresolved_names}
                jobs.update({executor.submit(lookup, "id", pid): pid for pid in unresolved_ids})
                done, pending = concurrent.futures.wait(jobs, timeout=8.0)
                for future in done:
                    try:
                        future.result()
                    except Exception as exc:
                        self._lookup_errors.add(jobs[future])
                        logger.warning("Поиск профиля недоступен: %s", exc)
                for future in pending:
                    self._lookup_errors.add(jobs[future])
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)

        results: List[PlayerResult] = []
        seen_exact_inputs: Dict[str, PlayerResult] = {}
        seen_player_ids: Dict[int, PlayerResult] = {}

        for item in items:
            normalized_raw = item.raw_text.strip().lower()

            # 1. Exact raw text duplicate check
            if normalized_raw in seen_exact_inputs:
                prior = seen_exact_inputs[normalized_raw]
                res = PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.DUPLICATE,
                    player_id=prior.player_id,
                    name=prior.name,
                    avg_rating=prior.avg_rating,
                    reviews_count=prior.reviews_count,
                    avatar_url=prior.avatar_url,
                    profile_url=prior.profile_url,
                    duplicate_of_id=prior.player_id,
                    duplicate_of_name=prior.name,
                    resolution_note=f"Точный дубликат строки {prior.line_number} ('{prior.input_text}')",
                )
                results.append(res)
                continue

            # 2. Match
            key = (
                item.extracted_id
                if item.extracted_id is not None
                else (item.extracted_name or item.raw_text).strip().lower()
            )
            if key in self._lookup_errors:
                res = PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.AMBIGUOUS,
                    resolution_note="Поиск временно недоступен; повторите запрос или укажите ID",
                )
            else:
                try:
                    res = self._match_single(
                        item, resolve_ambiguous_strategy, allow_online=allow_online
                    )
                except ShinriNetworkError:
                    res = PlayerResult(
                        input_text=item.raw_text,
                        line_number=item.line_number,
                        status=MatchStatus.AMBIGUOUS,
                        resolution_note="Поиск временно недоступен",
                    )

            # 3. Check resolved player ID
            if res.player_id and res.status in (MatchStatus.MATCHED, MatchStatus.UNRATED):
                if res.player_id in seen_player_ids:
                    prior = seen_player_ids[res.player_id]
                    dup_res = PlayerResult(
                        input_text=item.raw_text,
                        line_number=item.line_number,
                        status=MatchStatus.DUPLICATE,
                        player_id=res.player_id,
                        name=res.name,
                        avg_rating=res.avg_rating,
                        reviews_count=res.reviews_count,
                        avatar_url=res.avatar_url,
                        profile_url=res.profile_url,
                        duplicate_of_id=prior.player_id,
                        duplicate_of_name=prior.name,
                        resolution_note=f"Совпадает с уже обработанным игроком '{prior.name}' (ID: {prior.player_id}) из строки {prior.line_number}",
                    )
                    results.append(dup_res)
                    seen_exact_inputs[normalized_raw] = dup_res
                    continue
                else:
                    seen_player_ids[res.player_id] = res

            seen_exact_inputs[normalized_raw] = res
            results.append(res)

        return results

    def _match_single(
        self,
        item: ParseItem,
        resolve_ambiguous_strategy: str,
        allow_online: bool = True,
    ) -> PlayerResult:
        # A. By ID
        if item.extracted_id is not None:
            pid = item.extracted_id
            cached = self.client.find_by_id(pid)
            if cached:
                return PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.MATCHED,
                    player_id=cached["id"],
                    name=cached["name"],
                    avg_rating=cached["avg"],
                    reviews_count=cached["count"],
                    avatar_url=cached.get("avatar_url"),
                    profile_url=cached["profile_url"],
                )

            if allow_online:
                online = self.client.fetch_player_online_by_id(pid)
                if online:
                    if online["is_unrated"]:
                        return PlayerResult(
                            input_text=item.raw_text,
                            line_number=item.line_number,
                            status=MatchStatus.UNRATED,
                            player_id=online["id"],
                            name=online["name"],
                            avg_rating=None,
                            reviews_count=0,
                            avatar_url=online.get("avatar_url"),
                            profile_url=online["profile_url"],
                            resolution_note="Профиль существует, но ещё не имеет отзывов (рейтинг недоступен)",
                        )
                    else:
                        return PlayerResult(
                            input_text=item.raw_text,
                            line_number=item.line_number,
                            status=MatchStatus.MATCHED,
                            player_id=online["id"],
                            name=online["name"],
                            avg_rating=online["avg"],
                            reviews_count=online["count"],
                            avatar_url=online.get("avatar_url"),
                            profile_url=online["profile_url"],
                        )

            return PlayerResult(
                input_text=item.raw_text,
                line_number=item.line_number,
                status=MatchStatus.MISSING,
                resolution_note=f"Профиль с ID {pid} не найден на shinrireviews.com",
            )

        # B. By Name
        name = item.extracted_name or item.raw_text
        matches = self.client.find_by_name(name)

        # Fallback: if not found, check if stripping a clan tag (e.g. [DR] Nick) matches
        if not matches:
            try:
                from .analytics import ClanDetector

                clan_tag, clean_name = ClanDetector.extract_clan(name)
                if clan_tag and clean_name:
                    clean_matches = self.client.find_by_name(clean_name)
                    if clean_matches:
                        matches = clean_matches
            except Exception:
                pass

        if len(matches) == 1:
            m = matches[0]
            return PlayerResult(
                input_text=item.raw_text,
                line_number=item.line_number,
                status=MatchStatus.MATCHED,
                player_id=m["id"],
                name=m["name"],
                avg_rating=m["avg"],
                reviews_count=m["count"],
                avatar_url=m.get("avatar_url"),
                profile_url=m["profile_url"],
            )

        if len(matches) > 1:
            sorted_candidates = sorted(matches, key=lambda x: (-x["count"], x["id"]))

            if resolve_ambiguous_strategy == "most_reviews":
                chosen = sorted_candidates[0]
                other_candidates = [
                    f"ID: {c['id']} ({c['name']}, {c['count']} отз., ★ {c['avg']})"
                    for c in sorted_candidates[1:]
                ]
                note = (
                    f"Автоматически выбран профиль с наибольшим числом отзывов: "
                    f"ID {chosen['id']} ({chosen['count']} отз.). "
                    f"Другие совпадения: {', '.join(other_candidates)}"
                )
                return PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.MATCHED,
                    player_id=chosen["id"],
                    name=chosen["name"],
                    avg_rating=chosen["avg"],
                    reviews_count=chosen["count"],
                    avatar_url=chosen.get("avatar_url"),
                    profile_url=chosen["profile_url"],
                    candidates=sorted_candidates,
                    resolution_note=note,
                )
            else:
                return PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.AMBIGUOUS,
                    candidates=sorted_candidates,
                    resolution_note=f"Найдено {len(sorted_candidates)} профилей с данным именем",
                )

        # 3. Not in ratings -> online lookup
        if allow_online:
            online_exact, search_candidates = self.client.fetch_player_online_by_name(name)

            if online_exact:
                if online_exact["is_unrated"]:
                    return PlayerResult(
                        input_text=item.raw_text,
                        line_number=item.line_number,
                        status=MatchStatus.UNRATED,
                        player_id=online_exact["id"],
                        name=online_exact["name"],
                        avg_rating=None,
                        reviews_count=0,
                        avatar_url=online_exact.get("avatar_url"),
                        profile_url=online_exact["profile_url"],
                        resolution_note="Игрок найден в базе, но не имеет отзывов (0 отзывов)",
                    )
                else:
                    return PlayerResult(
                        input_text=item.raw_text,
                        line_number=item.line_number,
                        status=MatchStatus.MATCHED,
                        player_id=online_exact["id"],
                        name=online_exact["name"],
                        avg_rating=online_exact["avg"],
                        reviews_count=online_exact["count"],
                        avatar_url=online_exact.get("avatar_url"),
                        profile_url=online_exact["profile_url"],
                    )

            if search_candidates:
                return PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.AMBIGUOUS,
                    candidates=search_candidates,
                    resolution_note=f"Точного совпадения нет. Найдено похожих профилей: {len(search_candidates)}",
                )

        # 4. Try Fuzzy matching against rated player database
        fuzzy_match = self.fuzzy.find_best_match(name, cutoff=0.75)
        if fuzzy_match:
            cand, ratio = fuzzy_match
            if ratio >= 0.82:
                # High confidence typo fix
                return PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.MATCHED,
                    player_id=cand["id"],
                    name=cand["name"],
                    avg_rating=cand["avg"],
                    reviews_count=cand["count"],
                    avatar_url=cand.get("avatar_url"),
                    profile_url=cand["profile_url"],
                    resolution_note=f"Автоматически исправлена опечатка: '{name}' → '{cand['name']}' (сходство {int(ratio*100)}%)",
                )
            else:
                # Moderate confidence: mark as ambiguous suggestion
                return PlayerResult(
                    input_text=item.raw_text,
                    line_number=item.line_number,
                    status=MatchStatus.AMBIGUOUS,
                    candidates=[cand],
                    resolution_note=f"Возможная опечатка: '{name}' похоже на '{cand['name']}' (сходство {int(ratio*100)}%)",
                )

        return PlayerResult(
            input_text=item.raw_text,
            line_number=item.line_number,
            status=MatchStatus.MISSING,
            resolution_note="Игрок с таким именем не найден на shinrireviews.com",
        )
