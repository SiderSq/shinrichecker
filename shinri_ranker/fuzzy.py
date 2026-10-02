"""
Fuzzy matching engine for player nicknames using Levenshtein similarity.
Automatically fixes typos in input names and OCR scans against the Shinri database.
Optimized with O(1) exact checking, candidate length pruning, and cached index tables.
"""

from __future__ import annotations
import difflib
from typing import Any, Dict, List, Optional, Tuple

from .client import ShinriClient


class FuzzyMatcher:
    """
    High-performance fuzzy matching engine for player nicknames.
    Matches queries against the 5,414+ player database with mathematical pruning.
    """

    def __init__(self, client: ShinriClient):
        self.client = client
        self._cached_names: Optional[List[str]] = None
        self._names_by_len: Dict[int, List[str]] = {}
        self._cached_loaded_at: Optional[float] = None
        self._query_cache: Dict[Tuple[str, float], Optional[Tuple[Dict[str, Any], float]]] = {}

    def _ensure_cache(self) -> List[str]:
        if not self.client.is_loaded:
            self.client.load_ratings()

        client_loaded_at = getattr(self.client, "_loaded_at", None)
        if self._cached_names is None or self._cached_loaded_at != client_loaded_at:
            self._cached_names = list(self.client._by_name_lower.keys())
            self._names_by_len = {}
            for name in self._cached_names:
                self._names_by_len.setdefault(len(name), []).append(name)
            self._cached_loaded_at = client_loaded_at
            self._query_cache.clear()

        return self._cached_names

    def find_best_match(self, query: str, cutoff: float = 0.72) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Finds the closest known player name in the ratings database.
        Returns (matched_record, similarity_ratio) or None if no match meets cutoff.
        """
        query_clean = query.strip()
        query_lower = query_clean.lower()
        if not query_lower:
            return None

        # O(1) Fast path for exact match
        if query_lower in self.client._by_name_lower:
            records = self.client._by_name_lower[query_lower]
            if records:
                chosen = max(records, key=lambda x: x.get("count", 0))
                return chosen, 1.0

        cache_key = (query_lower, cutoff)
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        all_names = self._ensure_cache()
        if not all_names:
            return None

        # O(1) Homoglyph check for OCR / keyboard typos (Cyrillic to Latin)
        HOMOGLYPH_CYR_TO_LAT = str.maketrans("асеоррухііј", "aceoppyxiij")
        trans_lower = query_lower.translate(HOMOGLYPH_CYR_TO_LAT)
        if trans_lower != query_lower and trans_lower in self.client._by_name_lower:
            records = self.client._by_name_lower[trans_lower]
            if records:
                chosen = max(records, key=lambda x: x.get("count", 0))
                res = (chosen, 0.98)
                self._query_cache[cache_key] = res
                return res

        # Mathematical pruning: only fetch candidates with length difference within tolerance
        q_len = len(query_lower)
        if q_len <= 4:
            max_len_diff = 1
            effective_cutoff = max(cutoff, 0.82)
        elif q_len <= 5:
            max_len_diff = 1
            effective_cutoff = max(cutoff, 0.78)
        elif q_len <= 6:
            max_len_diff = 1
            effective_cutoff = max(cutoff, 0.75)
        else:
            max_len_diff = max(2, int(q_len * (1.0 - cutoff) + 2))
            effective_cutoff = cutoff

        min_len = max(1, q_len - max_len_diff)
        max_len = q_len + max_len_diff

        candidate_pool: List[str] = []
        for l in range(min_len, max_len + 1):
            candidate_pool.extend(self._names_by_len.get(l, ()))

        if not candidate_pool:
            candidate_pool = all_names

        # Quick close matches via difflib
        closest = difflib.get_close_matches(query_lower, candidate_pool, n=1, cutoff=effective_cutoff)
        if not closest:
            self._query_cache[cache_key] = None
            return None

        matched_lower = closest[0]
        len_diff = abs(q_len - len(matched_lower))
        if q_len <= 5 and len_diff >= 2:
            self._query_cache[cache_key] = None
            return None

        ratio = difflib.SequenceMatcher(None, query_lower, matched_lower).ratio()
        if ratio < effective_cutoff:
            self._query_cache[cache_key] = None
            return None

        records = self.client._by_name_lower.get(matched_lower, [])
        if not records:
            self._query_cache[cache_key] = None
            return None

        chosen = max(records, key=lambda x: x.get("count", 0))
        res = (chosen, round(ratio, 2))
        self._query_cache[cache_key] = res
        return res

    def find_top_matches(
        self, query: str, limit: int = 5, cutoff: float = 0.60
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Finds up to `limit` closest matches meeting the similarity cutoff."""
        all_names = self._ensure_cache()
        if not all_names:
            return []

        query_lower = query.strip().lower()
        if not query_lower:
            return []

        q_len = len(query_lower)
        max_len_diff = max(3, int(q_len * (1.0 - cutoff) + 3))
        min_len = max(1, q_len - max_len_diff)
        max_len = q_len + max_len_diff

        candidate_pool: List[str] = []
        for l in range(min_len, max_len + 1):
            candidate_pool.extend(self._names_by_len.get(l, ()))
        if not candidate_pool:
            candidate_pool = all_names

        closest = difflib.get_close_matches(query_lower, candidate_pool, n=limit, cutoff=cutoff)
        results: List[Tuple[Dict[str, Any], float]] = []

        for name_lower in closest:
            ratio = difflib.SequenceMatcher(None, query_lower, name_lower).ratio()
            records = self.client._by_name_lower.get(name_lower, [])
            if records:
                chosen = max(records, key=lambda x: x.get("count", 0))
                results.append((chosen, round(ratio, 2)))

        return sorted(results, key=lambda x: -x[1])
