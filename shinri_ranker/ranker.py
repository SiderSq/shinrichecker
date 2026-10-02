"""
Ranking engine supporting both Classic Average and Bayesian Average ranking,
avatar integration, review count weighting, and comprehensive reporting.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .matcher import MatchStatus, PlayerResult


@dataclass
class RankedPlayer:
    rank: int
    player_id: Optional[int]
    name: str
    avg_rating: Optional[float]
    bayesian_score: Optional[float]
    reviews_count: int
    profile_url: str
    avatar_url: str
    original_input: str
    verified_avg: Optional[float] = None
    verified_count: int = 0
    top_review: Optional[Dict[str, Any]] = None
    note: Optional[str] = None
    status: str = "matched"
    status_label: str = "В рейтинге"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "player_id": self.player_id,
            "name": self.name,
            "avg_rating": round(self.avg_rating, 2) if self.avg_rating is not None else None,
            "bayesian_score": round(self.bayesian_score, 2) if self.bayesian_score is not None else None,
            "reviews_count": self.reviews_count,
            "profile_url": self.profile_url,
            "avatar_url": self.avatar_url,
            "original_input": self.original_input,
            "verified_avg": round(self.verified_avg, 2) if self.verified_avg is not None else None,
            "verified_count": self.verified_count,
            "top_review": self.top_review,
            "note": self.note,
            "status": self.status,
            "status_label": self.status_label,
        }


@dataclass
class RankingReport:
    top_n: int
    min_reviews: int
    ranking_mode: str  # "bayesian" or "classic"
    global_avg: float
    m_confidence: int
    total_inputs: int
    unique_inputs: int
    best_players: List[RankedPlayer]
    worst_players: List[RankedPlayer]
    unrated_players: List[PlayerResult]
    ambiguous_players: List[PlayerResult]
    missing_players: List[PlayerResult]
    duplicates: List[PlayerResult]
    match_players: Optional[List[RankedPlayer]] = None

    def to_dict(self) -> Dict[str, Any]:
        unified = self.match_players if self.match_players is not None else self.best_players
        return {
            "config": {
                "top_n": self.top_n,
                "min_reviews": self.min_reviews,
                "ranking_mode": self.ranking_mode,
                "global_avg": self.global_avg,
                "m_confidence": self.m_confidence,
            },
            "summary": {
                "total_inputs": self.total_inputs,
                "unique_inputs": self.unique_inputs,
                "match_count": len(unified),
                "best_count": len(self.best_players),
                "worst_count": len(self.worst_players),
                "unrated_count": len(self.unrated_players),
                "ambiguous_count": len(self.ambiguous_players),
                "missing_count": len(self.missing_players),
                "duplicates_count": len(self.duplicates),
            },
            "players": [p.to_dict() for p in unified],
            "match_players": [p.to_dict() for p in unified],
            "best_players": [p.to_dict() for p in self.best_players],
            "worst_players": [p.to_dict() for p in self.worst_players],
            "unrated_players": [p.to_dict() for p in self.unrated_players],
            "ambiguous_players": [p.to_dict() for p in self.ambiguous_players],
            "missing_players": [p.to_dict() for p in self.missing_players],
            "duplicates": [p.to_dict() for p in self.duplicates],
        }


class Ranker:
    """Computes player rankings with Bayesian formula and classic modes."""

    @staticmethod
    def calculate_bayesian_score(avg: float, count: int, global_avg: float = 4.80, m: int = 5) -> float:
        """
        Bayesian Average calculation:
        R_bayes = (v * avg + m * global_avg) / (v + m)
        """
        if count <= 0:
            return 0.0
        return (count * avg + m * global_avg) / (count + m)

    @classmethod
    def generate_report(
        cls,
        results: List[PlayerResult],
        top_n: int = 10,
        min_reviews: int = 1,
        ranking_mode: str = "bayesian",  # "bayesian" or "classic"
        global_avg: float = 4.80,
        m_confidence: int = 5,
    ) -> RankingReport:
        duplicates: List[PlayerResult] = []
        unrated_players: List[PlayerResult] = []
        ambiguous_players: List[PlayerResult] = []
        missing_players: List[PlayerResult] = []
        eligible_rated: List[PlayerResult] = []

        total_inputs = len(results)

        for res in results:
            if res.status == MatchStatus.DUPLICATE:
                duplicates.append(res)
            elif res.status == MatchStatus.MISSING:
                missing_players.append(res)
            elif res.status == MatchStatus.AMBIGUOUS:
                ambiguous_players.append(res)
            elif res.status == MatchStatus.UNRATED:
                unrated_players.append(res)
            elif res.status == MatchStatus.MATCHED:
                count = res.reviews_count or 0
                if count >= min_reviews and res.avg_rating is not None:
                    eligible_rated.append(res)
                else:
                    unrated_players.append(res)

        unique_inputs = total_inputs - len(duplicates)

        # Precompute bayesian scores
        player_scores: Dict[int, float] = {}
        for p in eligible_rated:
            pid = p.player_id or 0
            avg = p.avg_rating or 0.0
            cnt = p.reviews_count or 0
            player_scores[pid] = cls.calculate_bayesian_score(avg, cnt, global_avg, m_confidence)

        # 1. Best players sorting
        if ranking_mode == "bayesian":
            sorted_best = sorted(
                eligible_rated,
                key=lambda x: (
                    -player_scores.get(x.player_id or 0, 0.0),
                    -(x.reviews_count or 0),
                    -(x.avg_rating or 0.0),
                    (x.player_id or 0),
                ),
            )
        else:
            sorted_best = sorted(
                eligible_rated,
                key=lambda x: (
                    -(x.avg_rating or 0.0),
                    -(x.reviews_count or 0),
                    (x.player_id or 0),
                ),
            )

        best_players: List[RankedPlayer] = []
        for idx, p in enumerate(sorted_best[:top_n], start=1):
            pid = p.player_id or 0
            avg = p.avg_rating or 0.0
            bayes = player_scores.get(pid, avg)
            avatar_url = p.avatar_url or "https://shinrireviews.com/assets/default-BEeM81pZ.png"

            best_players.append(
                RankedPlayer(
                    rank=idx,
                    player_id=pid,
                    name=p.name or p.input_text,
                    avg_rating=avg,
                    bayesian_score=bayes,
                    reviews_count=p.reviews_count or 0,
                    profile_url=p.profile_url or f"https://shinrireviews.com/p/{pid}",
                    avatar_url=avatar_url,
                    original_input=p.input_text,
                    note=p.resolution_note,
                )
            )

        # 2. Worst players sorting
        if ranking_mode == "bayesian":
            # For worst, we want lower bayesian score, or lower avg weighted by reviews
            sorted_worst = sorted(
                eligible_rated,
                key=lambda x: (
                    player_scores.get(x.player_id or 0, 999.0),
                    -(x.reviews_count or 0),
                    (x.avg_rating or 999.0),
                    (x.player_id or 0),
                ),
            )
        else:
            sorted_worst = sorted(
                eligible_rated,
                key=lambda x: (
                    (x.avg_rating or 999.0),
                    -(x.reviews_count or 0),
                    (x.player_id or 0),
                ),
            )

        worst_players: List[RankedPlayer] = []
        for idx, p in enumerate(sorted_worst[:top_n], start=1):
            pid = p.player_id or 0
            avg = p.avg_rating or 0.0
            bayes = player_scores.get(pid, avg)
            avatar_url = p.avatar_url or "https://shinrireviews.com/assets/default-BEeM81pZ.png"

            worst_players.append(
                RankedPlayer(
                    rank=idx,
                    player_id=pid,
                    name=p.name or p.input_text,
                    avg_rating=avg,
                    bayesian_score=bayes,
                    reviews_count=p.reviews_count or 0,
                    profile_url=p.profile_url or f"https://shinrireviews.com/p/{pid}",
                    avatar_url=avatar_url,
                    original_input=p.input_text,
                    note=p.resolution_note,
                )
            )

        # 3. Unified Match Players (all participants from input in a single list)
        match_players: List[RankedPlayer] = []
        rank_counter = 1

        # A. Rated players (sorted according to ranking_mode)
        for p in sorted_best:
            pid = p.player_id or 0
            avg = p.avg_rating or 0.0
            bayes = player_scores.get(pid, avg)
            avatar_url = p.avatar_url or "https://shinrireviews.com/assets/default-LZMr4ZDr.png"
            match_players.append(
                RankedPlayer(
                    rank=rank_counter,
                    player_id=pid,
                    name=p.name or p.input_text,
                    avg_rating=avg,
                    bayesian_score=bayes,
                    reviews_count=p.reviews_count or 0,
                    profile_url=p.profile_url or f"https://shinrireviews.com/p/{pid}",
                    avatar_url=avatar_url,
                    original_input=p.input_text,
                    note=p.resolution_note,
                    status="matched",
                    status_label="В рейтинге",
                )
            )
            rank_counter += 1

        # B. Unrated players (0 reviews or below threshold)
        for p in unrated_players:
            pid = p.player_id or 0
            avatar_url = p.avatar_url or "https://shinrireviews.com/assets/default-LZMr4ZDr.png"
            match_players.append(
                RankedPlayer(
                    rank=rank_counter,
                    player_id=pid if pid > 0 else None,
                    name=p.name or p.input_text,
                    avg_rating=p.avg_rating if (p.avg_rating and (p.reviews_count or 0) > 0) else None,
                    bayesian_score=None,
                    reviews_count=p.reviews_count or 0,
                    profile_url=p.profile_url or (f"https://shinrireviews.com/p/{pid}" if pid else ""),
                    avatar_url=avatar_url,
                    original_input=p.input_text,
                    note=p.resolution_note or "Нет отзывов (0 отзывов)",
                    status="unrated",
                    status_label="Нет оценок",
                )
            )
            rank_counter += 1

        # C. Missing players (profile not found in database)
        for p in missing_players:
            match_players.append(
                RankedPlayer(
                    rank=rank_counter,
                    player_id=None,
                    name=p.input_text,
                    avg_rating=None,
                    bayesian_score=None,
                    reviews_count=0,
                    profile_url="",
                    avatar_url="https://shinrireviews.com/assets/default-LZMr4ZDr.png",
                    original_input=p.input_text,
                    note=p.resolution_note or "Профиль не найден в базе данных",
                    status="missing",
                    status_label="Не найден в базе",
                )
            )
            rank_counter += 1

        # D. Ambiguous players (if manual resolution)
        for p in ambiguous_players:
            match_players.append(
                RankedPlayer(
                    rank=rank_counter,
                    player_id=None,
                    name=p.name or p.input_text,
                    avg_rating=None,
                    bayesian_score=None,
                    reviews_count=0,
                    profile_url="",
                    avatar_url="https://shinrireviews.com/assets/default-LZMr4ZDr.png",
                    original_input=p.input_text,
                    note=p.resolution_note or "Неоднозначное совпадение (омоним)",
                    status="ambiguous",
                    status_label="Омоним",
                )
            )
            rank_counter += 1

        # E. Duplicate players
        for p in duplicates:
            match_players.append(
                RankedPlayer(
                    rank=rank_counter,
                    player_id=p.player_id,
                    name=p.name or p.input_text,
                    avg_rating=p.avg_rating,
                    bayesian_score=None,
                    reviews_count=p.reviews_count or 0,
                    profile_url=p.profile_url or "",
                    avatar_url=p.avatar_url or "https://shinrireviews.com/assets/default-LZMr4ZDr.png",
                    original_input=p.input_text,
                    note=f"Повтор игрока (ID {p.duplicate_of_id})" if p.duplicate_of_id else "Повторяющаяся запись",
                    status="duplicate",
                    status_label="Дубликат",
                )
            )
            rank_counter += 1

        return RankingReport(
            top_n=top_n,
            min_reviews=min_reviews,
            ranking_mode=ranking_mode,
            global_avg=global_avg,
            m_confidence=m_confidence,
            total_inputs=total_inputs,
            unique_inputs=unique_inputs,
            best_players=best_players,
            worst_players=worst_players,
            unrated_players=unrated_players,
            ambiguous_players=ambiguous_players,
            missing_players=missing_players,
            duplicates=duplicates,
            match_players=match_players,
        )

    @classmethod
    def sort_match_players(
        cls,
        players: List[RankedPlayer],
        sort_order: str = "desc",
        ranking_mode: str = "bayesian",
    ) -> List[RankedPlayer]:
        """
        Sorts match players:
        - "desc" (Best to Worst): Highest score -> Lowest score, then unrated/missing/duplicates.
        - "asc" (Worst to Best): Lowest score -> Highest score, then unrated/missing/duplicates.
        Ranks are renumbered 1..N.
        """
        # Separate rated from unrated/missing/duplicates
        if ranking_mode == "bayesian":
            rated = [p for p in players if p.status == "matched" and p.bayesian_score is not None]
        else:
            rated = [p for p in players if p.status == "matched" and p.avg_rating is not None]
        non_rated = [p for p in players if p not in rated]

        if sort_order == "asc":
            if ranking_mode == "bayesian":
                rated_sorted = sorted(
                    rated,
                    key=lambda x: (
                        x.bayesian_score if x.bayesian_score is not None else 999.0,
                        -(x.reviews_count or 0),
                        x.avg_rating if x.avg_rating is not None else 999.0,
                        (x.player_id or 0),
                    ),
                )
            else:
                rated_sorted = sorted(
                    rated,
                    key=lambda x: (
                        x.avg_rating if x.avg_rating is not None else 999.0,
                        -(x.reviews_count or 0),
                        (x.player_id or 0),
                    ),
                )
        else:
            if ranking_mode == "bayesian":
                rated_sorted = sorted(
                    rated,
                    key=lambda x: (
                        -(x.bayesian_score if x.bayesian_score is not None else -1.0),
                        -(x.reviews_count or 0),
                        -(x.avg_rating if x.avg_rating is not None else -1.0),
                        (x.player_id or 0),
                    ),
                )
            else:
                rated_sorted = sorted(
                    rated,
                    key=lambda x: (
                        -(x.avg_rating if x.avg_rating is not None else -1.0),
                        -(x.reviews_count or 0),
                        (x.player_id or 0),
                    ),
                )

        combined = rated_sorted + non_rated
        result = []
        for idx, p in enumerate(combined, start=1):
            cloned = RankedPlayer(
                rank=idx,
                player_id=p.player_id,
                name=p.name,
                avg_rating=p.avg_rating,
                bayesian_score=p.bayesian_score,
                reviews_count=p.reviews_count,
                profile_url=p.profile_url,
                avatar_url=p.avatar_url,
                original_input=p.original_input,
                verified_avg=p.verified_avg,
                verified_count=p.verified_count,
                top_review=p.top_review,
                note=p.note,
                status=p.status,
                status_label=p.status_label,
            )
            result.append(cloned)
        return result

