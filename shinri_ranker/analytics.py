"""
Advanced analytics for Shinri Reviews & Danganronpa Online (DRO):
- Fair Team Balancer with Elo & Win Probability (Fair Matchmaking)
- Clan & Tag Meta-Analytics (Teaming & Synergy Detection)
- Tournament Bracket Generator (Single Elimination & Round Robin)
- Review Sentiment & Keyword Behavior Analysis
- Lobby Safety & Toxicity Meter
- Review Farming / Mutual Review Ring Detector
- DRO Player Card & Title Archetype Generator
"""

from __future__ import annotations
from copy import deepcopy
import math
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .client import ShinriClient


class EloConverter:
    """Converts Shinri Reviews ratings (1.0 - 5.0) into competitive Elo scores and calculates win probabilities."""

    @staticmethod
    def rating_to_elo(rating: float) -> int:
        """
        Maps a 1.0 - 5.0 rating to an 800 - 2200 Elo rating.
        1.0 -> 800
        3.0 -> 1500
        4.0 -> 1850
        5.0 -> 2200
        """
        clamped = max(1.0, min(5.0, float(rating)))
        return int(round(800.0 + (clamped - 1.0) * 350.0))

    @staticmethod
    def win_probability(elo_a: float, elo_b: float) -> Tuple[float, float]:
        """Calculates expected win percentage for team A vs team B using logistic Elo equation."""
        diff = float(elo_b - elo_a)
        prob_a = 1.0 / (1.0 + math.pow(10.0, diff / 400.0))
        pct_a = round(prob_a * 100.0, 1)
        pct_b = round((1.0 - prob_a) * 100.0, 1)
        return pct_a, pct_b


class ClanDetector:
    """Identifies clan tags, prefixes, and potential teaming clusters in a room."""

    PREFIX_PATTERNS = [
        re.compile(r"^\[([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\]\s*(.+)$"),
        re.compile(r"^\{([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\}\s*(.+)$"),
        re.compile(r"^\(([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\)\s*(.+)$"),
        re.compile(r"^\|([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\|\s*(.+)$"),
        re.compile(r"^([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\|(.+)$"),
        re.compile(r"^\^([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\^\s*(.+)$"),
        re.compile(r"^([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})_(.+)$"),
    ]

    SUFFIX_PATTERNS = [
        re.compile(r"^(.+?)\s*\[([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\]$"),
        re.compile(r"^(.+?)\s*\{([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\}$"),
        re.compile(r"^(.+?)\s*\(([a-zA-Zа-яА-ЯёЁ0-9_\-]{2,10})\)$"),
    ]

    CLAN_PATTERNS = PREFIX_PATTERNS

    @classmethod
    def extract_clan(cls, name: str) -> Tuple[Optional[str], str]:
        """Extracts clan tag if present and returns (clan_tag_upper, clean_name)."""
        clean_name = name.strip()
        for pattern in cls.PREFIX_PATTERNS:
            m = pattern.match(clean_name)
            if m:
                tag = m.group(1).upper()
                player_nick = m.group(2).strip()
                if len(tag) >= 2 and player_nick:
                    return tag, player_nick
        for pattern in cls.SUFFIX_PATTERNS:
            m = pattern.match(clean_name)
            if m:
                player_nick = m.group(1).strip()
                tag = m.group(2).upper()
                if len(tag) >= 2 and player_nick:
                    return tag, player_nick
        return None, clean_name

    @classmethod
    def analyze_clans(cls, players: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Groups players by clan tag, computes clan averages, and alerts on teaming clusters."""
        clans_map: Dict[str, List[Dict[str, Any]]] = {}

        for p in deepcopy(players):
            name = p.get("name") or p.get("input_text", "")
            tag, clean_name = cls.extract_clan(name)
            p["clan_tag"] = tag
            p["clean_name"] = clean_name
            if tag:
                clans_map.setdefault(tag, []).append(p)

        clan_summary = []
        teaming_warnings = []

        for tag, members in clans_map.items():
            ratings = [
                float(m.get("avg_rating") or m.get("avg") or 0.0)
                for m in members
                if (m.get("avg_rating") or m.get("avg"))
            ]
            avg_clan_score = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
            member_names = [m.get("name") or m.get("input_text", "Игрок") for m in members]

            clan_summary.append(
                {
                    "tag": tag,
                    "count": len(members),
                    "avg_rating": avg_clan_score,
                    "members": member_names,
                }
            )

            if len(members) >= 3:
                teaming_warnings.append(
                    {
                        "tag": tag,
                        "count": len(members),
                        "text": f"Клан '[{tag}]' представлен {len(members)} игроками ({', '.join(member_names)}). Общий тег; это не доказательство сговора.",
                    }
                )

        return {
            "clans": sorted(clan_summary, key=lambda c: -c["count"]),
            "teaming_warnings": teaming_warnings,
        }

    @classmethod
    def detect_clans(cls, players: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Returns a dict mapping clan_tag -> {count, avg_score, avg_elo, members}."""
        res = cls.analyze_clans(players)
        out = {}
        for c in res.get("clans", []):
            out[c["tag"]] = {
                "count": c["count"],
                "avg_score": c["avg_rating"],
                "avg_elo": (
                    EloConverter.rating_to_elo(c["avg_rating"]) if c["avg_rating"] > 0 else 1500
                ),
                "members": c["members"],
            }
        return out

    @classmethod
    def check_teaming_risk(cls, players: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Checks if any clan has teaming risk and returns status and warnings."""
        res = cls.analyze_clans(players)
        warnings = res.get("teaming_warnings", [])
        return {
            "is_risk": len(warnings) > 0,
            "warnings": warnings,
        }


class TeamBalancer:
    """Partitions a roster of players into 2 balanced teams with Elo and win probabilities."""

    @staticmethod
    def balance_teams(
        players: List[Dict[str, Any]],
        metric: str = "bayesian_score",  # "bayesian_score" or "avg_rating"
        equal_team_sizes: bool = True,
    ) -> Dict[str, Any]:
        """
        Balances players into Team Blue and Team Red.
        Uses snake greedy allocation + optimized 2-opt pairwise swaps.
        """
        players = deepcopy(players)
        if not players:
            return {
                "team_a": [],
                "team_b": [],
                "avg_a": 0.0,
                "avg_b": 0.0,
                "score_a": 0.0,
                "score_b": 0.0,
                "delta": 0.0,
                "fairness": 100.0,
                "elo_a": 1500,
                "elo_b": 1500,
                "win_prob_a": 50.0,
                "win_prob_b": 50.0,
            }

        # Extract score & tag clan
        def get_score(p: Dict[str, Any]) -> float:
            val = p.get(metric) or p.get("avg_rating") or p.get("avg") or 0.0
            return float(val)

        # Annotate with Elo & clan tag
        for p in players:
            sc = get_score(p)
            p["elo"] = EloConverter.rating_to_elo(sc)
            if "clan_tag" not in p:
                tag, _ = ClanDetector.extract_clan(p.get("name", ""))
                p["clan_tag"] = tag

        sorted_players = sorted(deepcopy(players), key=lambda p: -get_score(p))
        n = len(sorted_players)
        half = (n + 1) // 2
        other_half = n // 2

        team_a: List[Dict[str, Any]] = []
        team_b: List[Dict[str, Any]] = []
        score_a = 0.0
        score_b = 0.0

        # Snake greedy allocation
        for p in sorted_players:
            sc = get_score(p)
            if equal_team_sizes:
                if len(team_a) < half and (len(team_b) >= other_half or score_a <= score_b):
                    team_a.append(p)
                    score_a += sc
                else:
                    team_b.append(p)
                    score_b += sc
            else:
                if score_a <= score_b:
                    team_a.append(p)
                    score_a += sc
                else:
                    team_b.append(p)
                    score_b += sc

        # 2-opt pairwise swap optimization with early termination
        improved = True
        iterations = 0
        while improved and iterations < 40:
            iterations += 1
            improved = False
            current_diff = abs(score_a / max(1, len(team_a)) - score_b / max(1, len(team_b)))
            if current_diff < 0.05:
                break  # Optimal balance achieved

            best_swap = None

            for i, a in enumerate(team_a):
                sc_a = get_score(a)
                for j, b in enumerate(team_b):
                    sc_b = get_score(b)
                    new_score_a = score_a - sc_a + sc_b
                    new_score_b = score_b - sc_b + sc_a
                    new_diff = abs(
                        new_score_a / max(1, len(team_a)) - new_score_b / max(1, len(team_b))
                    )
                    if new_diff < current_diff - 1e-4:
                        current_diff = new_diff
                        best_swap = (i, j, new_score_a, new_score_b)
                        improved = True

            if best_swap:
                i, j, new_score_a, new_score_b = best_swap
                team_a[i], team_b[j] = team_b[j], team_a[i]
                score_a = new_score_a
                score_b = new_score_b

        avg_a = score_a / len(team_a) if team_a else 0.0
        avg_b = score_b / len(team_b) if team_b else 0.0
        delta = abs(avg_a - avg_b)
        fairness = max(0.0, min(100.0, 100.0 - (delta * 25.0)))

        # Calculate team Elo and Win Probability
        team_a_elo = int(round(sum(p["elo"] for p in team_a) / len(team_a))) if team_a else 1500
        team_b_elo = int(round(sum(p["elo"] for p in team_b) / len(team_b))) if team_b else 1500
        win_a, win_b = EloConverter.win_probability(team_a_elo, team_b_elo)

        return {
            "team_a": team_a,
            "team_b": team_b,
            "score_a": round(score_a, 2),
            "score_b": round(score_b, 2),
            "avg_a": round(avg_a, 2),
            "avg_b": round(avg_b, 2),
            "delta": round(delta, 2),
            "fairness": round(fairness, 1),
            "elo_a": team_a_elo,
            "elo_b": team_b_elo,
            "prediction_kind": "rating_heuristic_not_calibrated",
            "win_prob_a": win_a,
            "win_prob_b": win_b,
        }

    @classmethod
    def calculate_roster_stats(
        cls,
        team_a: List[Dict[str, Any]],
        team_b: List[Dict[str, Any]],
        metric: str = "bayesian_score",
    ) -> Dict[str, Any]:
        """Calculates balance, Elo, and win probability for custom/manually swapped rosters."""

        def get_score(p: Dict[str, Any]) -> float:
            val = p.get(metric) or p.get("avg_rating") or p.get("avg") or 0.0
            return float(val)

        for p in team_a + team_b:
            if "elo" not in p or not p["elo"]:
                p["elo"] = EloConverter.rating_to_elo(get_score(p))
            if "clan_tag" not in p:
                tag, _ = ClanDetector.extract_clan(p.get("name", ""))
                p["clan_tag"] = tag

        score_a = sum(get_score(p) for p in team_a)
        score_b = sum(get_score(p) for p in team_b)
        avg_a = score_a / len(team_a) if team_a else 0.0
        avg_b = score_b / len(team_b) if team_b else 0.0
        delta = abs(avg_a - avg_b)
        fairness = max(0.0, min(100.0, 100.0 - (delta * 25.0)))

        team_a_elo = int(round(sum(p["elo"] for p in team_a) / len(team_a))) if team_a else 1500
        team_b_elo = int(round(sum(p["elo"] for p in team_b) / len(team_b))) if team_b else 1500
        win_a, win_b = EloConverter.win_probability(team_a_elo, team_b_elo)

        return {
            "team_a": team_a,
            "team_b": team_b,
            "score_a": round(score_a, 2),
            "score_b": round(score_b, 2),
            "avg_a": round(avg_a, 2),
            "avg_b": round(avg_b, 2),
            "delta": round(delta, 2),
            "fairness": round(fairness, 1),
            "elo_a": team_a_elo,
            "elo_b": team_b_elo,
            "prediction_kind": "rating_heuristic_not_calibrated",
            "win_prob_a": win_a,
            "win_prob_b": win_b,
        }


class LobbySafetyMeter:
    """Calculates room toxicity & reliability index based on player ratings, unrated count, and clan teaming."""

    @classmethod
    def analyze_lobby(
        cls,
        ranked_players: List[Dict[str, Any]],
        unrated_players: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        all_players = list(ranked_players) + list(unrated_players)
        total = len(all_players)
        if total == 0:
            return {
                "score": 100,
                "status": "safe",
                "label": "Пустая комната",
                "warnings": [],
                "danger_count": 0,
                "unrated_count": 0,
                "clans": [],
            }

        danger_players = []
        unrated_count = len(unrated_players)
        warnings = []

        for p in ranked_players:
            avg = float(p.get("avg_rating") or p.get("avg") or 0.0)
            reviews = int(p.get("reviews_count") or p.get("count") or 0)
            name = p.get("name", "Игрок")

            # High risk condition: rating <= 2.2 with at least 2 reviews
            if avg <= 2.2 and reviews >= 2:
                danger_players.append(p)
                warnings.append(
                    {
                        "severity": "danger",
                        "player_id": p.get("player_id"),
                        "name": name,
                        "text": f"Игрок '{name}' имеет критически низкий рейтинг (балл {avg:.2f}, {reviews} отз.) — сигнал по отзывам, не прогноз поведения.",
                    }
                )
            elif avg <= 3.0:
                warnings.append(
                    {
                        "severity": "warning",
                        "player_id": p.get("player_id"),
                        "name": name,
                        "text": f"Игрок '{name}' имеет средний балл ниже среднего (балл {avg:.2f}).",
                    }
                )

        for p in unrated_players:
            name = p.get("name") or p.get("input_text", "Новичок")
            warnings.append(
                {
                    "severity": "info",
                    "name": name,
                    "text": f"Игрок '{name}' не имеет оценок (0 отзывов) — уровень игры неизвестен.",
                }
            )

        # Clan meta-analysis for teaming
        clan_info = ClanDetector.analyze_clans(all_players)
        for warn in clan_info.get("teaming_warnings", []):
            warnings.append(
                {
                    "severity": "warning",
                    "name": f"Клан [{warn['tag']}]",
                    "text": warn["text"],
                }
            )

        # Calculate safety index
        base_score = 100.0
        base_score -= len(danger_players) * 22.0
        base_score -= len(clan_info.get("teaming_warnings", [])) * 10.0

        unrated_ratio = unrated_count / total if total else 0
        base_score -= unrated_ratio * 12.0
        safety_score = max(5, min(100, int(round(base_score))))

        if safety_score >= 80:
            status = "safe"
            label = "Высокая надежность (Safe)"
            color = "#10b981"
        elif safety_score >= 55:
            status = "moderate"
            label = "Умеренный риск (Moderate)"
            color = "#f59e0b"
        else:
            status = "risk"
            label = "Низкий индекс отзывов (High Risk)"
            color = "#ef4444"

        return {
            "score": safety_score,
            "status": status,
            "label": label,
            "color": color,
            "danger_count": len(danger_players),
            "unrated_count": unrated_count,
            "warnings": warnings,
            "clans": clan_info.get("clans", []),
        }


class TournamentGenerator:
    """Generates seeded tournament brackets (Single Elimination) and Round Robin groups."""

    @classmethod
    def generate_bracket(
        cls,
        players: List[Dict[str, Any]],
        format_type: str = "single_elimination",
        metric: str = "bayesian_score",
    ) -> Dict[str, Any]:
        """
        Creates an organized tournament tournament fixture.
        Supports 4, 8, 16, or 32 player brackets with seeded matchups.
        """
        if len(players) < 2:
            return {"error": "Для турнирной сетки необходимо минимум 2 игрока."}

        def get_score(p: Dict[str, Any]) -> float:
            return float(p.get(metric) or p.get("avg_rating") or p.get("avg") or 0.0)

        sorted_players = sorted(deepcopy(players), key=lambda p: -get_score(p))

        if format_type == "round_robin":
            return cls._generate_round_robin(sorted_players)
        else:
            return cls._generate_single_elimination(sorted_players)

    @classmethod
    def generate_single_elimination(
        cls, players: List[Dict[str, Any]], metric: str = "bayesian_score"
    ) -> Dict[str, Any]:
        """Convenience method for single elimination brackets."""
        return cls.generate_bracket(players, format_type="single_elimination", metric=metric)

    @classmethod
    def generate_round_robin(
        cls, players: List[Dict[str, Any]], metric: str = "bayesian_score"
    ) -> Dict[str, Any]:
        """Convenience method for round robin groups."""
        return cls.generate_bracket(players, format_type="round_robin", metric=metric)

    @classmethod
    def _generate_single_elimination(cls, sorted_players: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(sorted_players)
        if n > 128:
            raise ValueError("Максимум 128 участников турнира")
        bracket_size = 1 << (n - 1).bit_length()
        seeded = sorted_players + [None] * (bracket_size - n)
        # Recursive seed order: highest seeds in opposite bracket halves.
        order = [1, 2]
        size = 2
        while size < bracket_size:
            size *= 2
            order = [seed for old in order for seed in (old, size + 1 - old)]
        pairs = list(zip(order[::2], order[1::2]))

        round_1_matches = []
        for idx, (s1, s2) in enumerate(pairs, start=1):
            p1 = seeded[s1 - 1]
            p2 = seeded[s2 - 1] if s2 <= len(seeded) else None

            if p1 is None:
                p1, p2, s1, s2 = p2, p1, s2, s1
            elo1 = EloConverter.rating_to_elo(p1.get("avg_rating") or p1.get("avg") or 4.0)
            elo2 = (
                EloConverter.rating_to_elo(p2.get("avg_rating") or p2.get("avg") or 4.0)
                if p2
                else 800
            )
            win1, win2 = EloConverter.win_probability(elo1, elo2) if p2 else (100.0, 0.0)

            p1_name = p1.get("name") or p1.get("input_text", "Игрок 1")
            p2_name = (p2.get("name") or p2.get("input_text", "Игрок 2")) if p2 else "BYE"
            pred_winner = p1_name if win1 >= win2 else (p2_name if p2 else p1_name)

            m_obj = {
                "match_id": f"R1-M{idx}",
                "match_num": idx,
                "seed_1": s1,
                "seed_2": s2,
                "player_1": p1,
                "player_2": p2,
                "player1": {
                    "name": p1_name,
                    "seed": s1,
                    "score": float(
                        p1.get("bayesian_score") or p1.get("avg_rating") or p1.get("avg") or 0.0
                    ),
                    "elo": elo1,
                    "avatar_url": p1.get("avatar_url"),
                    "is_bye": False,
                },
                "player2": {
                    "name": p2_name,
                    "seed": s2,
                    "score": (
                        float(
                            p2.get("bayesian_score") or p2.get("avg_rating") or p2.get("avg") or 0.0
                        )
                        if p2
                        else 0.0
                    ),
                    "elo": elo2,
                    "avatar_url": p2.get("avatar_url") if p2 else None,
                    "is_bye": p2 is None,
                },
                "win_chance_p1": win1,
                "win_chance_p2": win2,
                "win_prob1": round(win1 / 100.0, 2),
                "win_prob2": round(win2 / 100.0, 2),
                "predicted_winner": pred_winner,
            }
            round_1_matches.append(m_obj)

        def round_label(size):
            return (
                "Финал"
                if size == 2
                else (
                    "Полуфинал"
                    if size == 4
                    else ("Четвертьфинал" if size == 8 else f"1/{size//2} финала")
                )
            )

        round_name = round_label(bracket_size)
        rounds = [{"round_name": round_name, "matches": round_1_matches}]
        previous_ids = [m["match_id"] for m in round_1_matches]
        remaining, round_index = bracket_size // 2, 2
        while remaining >= 2:
            future = []
            for idx in range(remaining // 2):
                source_a, source_b = previous_ids[2 * idx : 2 * idx + 2]
                name_a, name_b = f"Победитель {source_a}", f"Победитель {source_b}"
                future.append(
                    {
                        "match_id": f"R{round_index}-M{idx+1}",
                        "match_num": idx + 1,
                        "source_match_1": source_a,
                        "source_match_2": source_b,
                        "player1": {"name": name_a, "is_bye": False},
                        "player2": {"name": name_b, "is_bye": False},
                        "player_1": None,
                        "player_2": None,
                        "predicted_winner": "—",
                        "pending": True,
                    }
                )
            rounds.append({"round_name": round_label(remaining), "matches": future})
            previous_ids = [m["match_id"] for m in future]
            remaining //= 2
            round_index += 1

        return {
            "format": "single_elimination",
            "bracket_size": bracket_size,
            "total_participants": n,
            "first_round_name": round_name,
            "matches": round_1_matches,
            "rounds": rounds,
        }

    @classmethod
    def _generate_round_robin(cls, sorted_players: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates balanced 4-player groups using snake seeding."""
        num_groups = max(1, math.ceil(len(sorted_players) / 4))
        groups: Dict[str, List[Dict[str, Any]]] = {chr(65 + i): [] for i in range(num_groups)}

        # Snake draft distribution across groups
        for idx, p in enumerate(sorted_players):
            cycle = idx // num_groups
            slot = idx % num_groups
            group_idx = slot if cycle % 2 == 0 else (num_groups - 1 - slot)
            group_letter = chr(65 + group_idx)
            groups[group_letter].append(p)

        fixtures = {}
        for g_letter, g_players in groups.items():
            g_matches = []
            m_id = 1
            for i in range(len(g_players)):
                for j in range(i + 1, len(g_players)):
                    p1 = g_players[i]
                    p2 = g_players[j]
                    elo1 = EloConverter.rating_to_elo(p1.get("avg_rating") or p1.get("avg") or 4.0)
                    elo2 = EloConverter.rating_to_elo(p2.get("avg_rating") or p2.get("avg") or 4.0)
                    win1, win2 = EloConverter.win_probability(elo1, elo2)
                    p1_name = p1.get("name") or p1.get("input_text", "Игрок")
                    p2_name = p2.get("name") or p2.get("input_text", "Игрок")
                    g_matches.append(
                        {
                            "match_id": f"Group-{g_letter}-M{m_id}",
                            "player_1": p1,
                            "player_2": p2,
                            "player1": p1_name,
                            "player2": p2_name,
                            "win_chance_p1": win1,
                            "win_chance_p2": win2,
                            "win_prob1": round(win1 / 100.0, 2),
                            "win_prob2": round(win2 / 100.0, 2),
                        }
                    )
                    m_id += 1

            for s_idx, p in enumerate(g_players, 1):
                p["seed"] = s_idx
                p["score"] = float(
                    p.get("bayesian_score") or p.get("avg_rating") or p.get("avg") or 0.0
                )
                p["elo"] = EloConverter.rating_to_elo(p.get("avg_rating") or p.get("avg") or 4.0)

            fixtures[f"Группа {g_letter}"] = {
                "group_name": f"Группа {g_letter}",
                "players": g_players,
                "matches": g_matches,
            }

        return {
            "format": "round_robin",
            "groups_count": num_groups,
            "groups": fixtures,
            "total_participants": len(sorted_players),
        }


class SentimentAnalyzer:
    """Analyzes player reviews for tone, sentiment polarity, and behavioral tags."""

    POSITIVE_WORDS = {
        "логика",
        "логичный",
        "детектив",
        "скилл",
        "скилловый",
        "тащит",
        "тащер",
        "алиби",
        "умный",
        "добрый",
        "топ",
        "лучший",
        "красавчик",
        "молодец",
        "активный",
        "сильный",
        "адекватный",
        "честный",
        "помогает",
        "опытный",
        "respect",
        "pro",
        "skill",
        "good",
        "nice",
        "friendly",
        "классно",
        "крутой",
        "супер",
        "четко",
        "гений",
        "базирован",
    }

    NEGATIVE_WORDS = {
        "токсик",
        "токсичный",
        "руин",
        "руинер",
        "лив",
        "ливер",
        "афк",
        "afk",
        "тролль",
        "троллит",
        "неадекват",
        "спам",
        "спамит",
        "бан",
        "слив",
        "сливает",
        "обман",
        "чсв",
        "нытик",
        "нытье",
        "оскорбляет",
        "clown",
        "feeder",
        "troll",
        "toxic",
        "leaver",
        "noob",
        "bad",
        "ливнул",
        "руинил",
        "тупой",
        "орет",
        "душит",
    }

    @classmethod
    def analyze_reviews(cls, reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyzes textual content of reviews and returns polarity and behavioral keywords."""
        if not reviews:
            return {
                "polarity": 0.0,
                "sentiment": "neutral",
                "label": "Нейтральный (отзывов нет)",
                "pos_hits": 0,
                "neg_hits": 0,
                "tags": [],
            }

        pos_count = 0
        neg_count = 0
        tag_freq: Dict[str, int] = {}

        for rev in reviews:
            text = (rev.get("text") or "").lower()
            tokens = re.findall(r"[a-zA-Zа-яА-ЯёЁ]+", text)
            for idx, tok in enumerate(tokens):
                negated = any(t in ("не", "not", "нет") for t in tokens[max(0, idx - 2) : idx])
                if negated:
                    continue
                if tok in cls.POSITIVE_WORDS:
                    pos_count += 1
                    tag_freq[tok] = tag_freq.get(tok, 0) + 1
                elif tok in cls.NEGATIVE_WORDS:
                    neg_count += 1
                    tag_freq[tok] = tag_freq.get(tok, 0) + 1

        total_hits = pos_count + neg_count
        if total_hits > 0:
            polarity = round((pos_count - neg_count) / float(total_hits), 2)
        else:
            polarity = 0.0

        if polarity >= 0.25:
            sentiment = "positive"
            label = "Позитивная репутация (Уважаемый игрок)"
        elif polarity <= -0.25:
            sentiment = "negative"
            label = "Токсичная репутация (Повышенное число жалоб)"
        else:
            sentiment = "neutral"
            label = "Нейтральная репутация"

        sorted_tags = [t[0] for t in sorted(tag_freq.items(), key=lambda x: -x[1])[:8]]

        return {
            "polarity": polarity,
            "sentiment": sentiment,
            "label": label,
            "pos_hits": pos_count,
            "neg_hits": neg_count,
            "tags": sorted_tags,
        }


class PlayerCardGenerator:
    """Generates archetypes, titles, and visual card metadata for DRO players."""

    @staticmethod
    def get_player_card(player: Dict[str, Any]) -> Dict[str, Any]:
        """Returns full trading-card metadata for a player."""
        avg = float(player.get("avg_rating") or player.get("avg") or 0.0)
        reviews = int(player.get("reviews_count") or player.get("count") or 0)
        elo = EloConverter.rating_to_elo(avg)

        if reviews == 0:
            title = "Скрытый Талант"
            archetype = "Новичок Академии"
            color = "#94a3b8"
            tier = "UNRATED"
        elif avg >= 4.95 and reviews >= 20:
            title = "Абсолютный Детектив"
            archetype = "Легенда Три Sanctum"
            color = "#f59e0b"
            tier = "S+"
        elif avg >= 4.80:
            title = "Мастер Дедукции"
            archetype = "Опытный Аналитик"
            color = "#10b981"
            tier = "S"
        elif avg >= 4.40:
            title = "Опытный Следователь"
            archetype = "Надежный Напарник"
            color = "#38bdf8"
            tier = "A"
        elif avg >= 3.50:
            title = "Рядовой Ученик"
            archetype = "Участник Класса"
            color = "#a78bfa"
            tier = "B"
        elif avg >= 2.50:
            title = "Сомнительный Свидетель"
            archetype = "Подозрительный Оппонент"
            color = "#fb923c"
            tier = "C"
        else:
            title = "Главный Подозреваемый"
            archetype = "Низкий рейтинг по отзывам"
            color = "#ef4444"
            tier = "D"

        tag, clean_name = ClanDetector.extract_clan(player.get("name", ""))

        return {
            "name": player.get("name", "Игрок"),
            "clean_name": clean_name,
            "clan_tag": tag,
            "player_id": player.get("player_id") or player.get("id"),
            "avg_rating": round(avg, 2),
            "reviews_count": reviews,
            "elo": elo,
            "title": title,
            "archetype": archetype,
            "tier": tier,
            "color": color,
            "avatar_url": player.get("avatar_url")
            or "https://shinrireviews.com/assets/default-BEeM81pZ.png",
            "profile_url": player.get("profile_url")
            or f"https://shinrireviews.com/p/{player.get('player_id')}",
        }


class ReviewRingDetector:
    """Detects mutual review circles between loaded players."""

    @classmethod
    def detect_mutual_reviews(
        cls,
        player_ids: List[int],
        client: ShinriClient,
    ) -> List[Dict[str, Any]]:
        """Identifies pairs of players where Player A reviewed Player B and Player B reviewed Player A."""
        if client.offline_mode or len(player_ids) < 2:
            return []

        reviewed_by: Dict[int, Set[int]] = {}
        names_map: Dict[int, str] = {}

        for pid in player_ids[:15]:  # limit deep checks for responsiveness
            p_info = client.find_by_id(pid)
            if p_info:
                names_map[pid] = p_info["name"]
            try:
                data = client._http_get_json(f"{client.API_URL}/reviews/{pid}")
                if data and isinstance(data, dict):
                    revs = data.get("reviews", [])
                    authors = set()
                    for r in revs:
                        auth_pid = r.get("authorPlayerId")
                        if auth_pid:
                            authors.add(int(auth_pid))
                    reviewed_by[pid] = authors
            except Exception:
                continue

        rings = []
        checked_pairs = set()

        for id_a in reviewed_by:
            for id_b in reviewed_by:
                if id_a >= id_b:
                    continue
                pair_key = (id_a, id_b)
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                # Check mutual
                a_reviews_b = id_a in reviewed_by.get(id_b, set())
                b_reviews_a = id_b in reviewed_by.get(id_a, set())

                if a_reviews_b and b_reviews_a:
                    rings.append(
                        {
                            "player_a_id": id_a,
                            "player_a_name": names_map.get(id_a, f"ID {id_a}"),
                            "player_b_id": id_b,
                            "player_b_name": names_map.get(id_b, f"ID {id_b}"),
                            "text": f"Обнаружены взаимные отзывы между {names_map.get(id_a, id_a)} и {names_map.get(id_b, id_b)}.",
                        }
                    )

        return rings
