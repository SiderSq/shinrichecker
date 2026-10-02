"""
API Client for https://shinrireviews.com.
Provides polite, cached, and offline-compatible access to player ratings,
detailed reviews, avatar mappings, and nick history.
"""

from __future__ import annotations
import json
import logging
import marshal
import os
import sys
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("shinri_client")

# Static mapping of DRO avatar character IDs to their live CDN assets on shinrireviews.com
AVATAR_CDN_MAP: Dict[str, str] = {
    "after_rain": "https://shinrireviews.com/assets/after_rain-Rq4JDj8p.png",
    "akane_1": "https://shinrireviews.com/assets/akane_1-DYRj1DWb.png",
    "akane_what_did_you_say": "https://shinrireviews.com/assets/akane_what_did_you_say-Cq8qKZvQ.png",
    "angie_1": "https://shinrireviews.com/assets/angie_1-BBv5Wtjh.png",
    "angie_2": "https://shinrireviews.com/assets/angie_2-DM8CgLKY.png",
    "aoi_1": "https://shinrireviews.com/assets/aoi_1-BTDdK6sQ.png",
    "byakuya_1": "https://shinrireviews.com/assets/byakuya_1-2ewXK9PN.png",
    "byakuya_2": "https://shinrireviews.com/assets/byakuya_2-BSOIDJt8.png",
    "byakuya_3-Dcz7rSk-": "https://shinrireviews.com/assets/byakuya_3-Dcz7rSk-.png",
    "byakuya_chibi_1": "https://shinrireviews.com/assets/byakuya_chibi_1-9irCej7B.png",
    "cc0826_bears_and_bunnies": "https://shinrireviews.com/assets/cc0826_bears_and_bunnies-BF67cjVq.png",
    "cc0826_brother_and_sister": "https://shinrireviews.com/assets/cc0826_brother_and_sister-DGe9GxYp.png",
    "cc0826_chiaki_vacation": "https://shinrireviews.com/assets/cc0826_chiaki_vacation-CBEzr8IS.png",
    "cc0826_ducklings": "https://shinrireviews.com/assets/cc0826_ducklings-vm5JF_bK.png",
    "cc0826_gundham_vacation": "https://shinrireviews.com/assets/cc0826_gundham_vacation-BTgsCoY7.png",
    "cc0826_hajime_vacation": "https://shinrireviews.com/assets/cc0826_hajime_vacation-BEaGhh9p.png",
    "cc0826_himiko_vacation": "https://shinrireviews.com/assets/cc0826_himiko_vacation-2aTq8ACZ.png",
    "cc0826_holiday_sparks": "https://shinrireviews.com/assets/cc0826_holiday_sparks-CTdBRqdo.png",
    "cc0826_ibuki_beach_season": "https://shinrireviews.com/assets/cc0826_ibuki_beach_season-D6fZgy6L.png",
    "cc0826_impostor_vacation": "https://shinrireviews.com/assets/cc0826_impostor_vacation-Dtbv4i08.png",
    "cc0826_incognito_vacation": "https://shinrireviews.com/assets/cc0826_incognito_vacation-DMsmqydy.png",
    "cc0826_nagisa_vacation": "https://shinrireviews.com/assets/cc0826_nagisa_vacation-BiFRrFzA.png",
    "cc0826_on_sunny_waves": "https://shinrireviews.com/assets/cc0826_on_sunny_waves-BkBcY6qb.png",
    "cc0826_pool_party": "https://shinrireviews.com/assets/cc0826_pool_party-U53XvVF7.png",
    "cc0826_punk_rock": "https://shinrireviews.com/assets/cc0826_punk_rock-BZlZxfHl.png",
    "cc0826_ryoma_vacation": "https://shinrireviews.com/assets/cc0826_ryoma_vacation-ImTfW7u9.png",
    "cc0826_scarlet_bloom": "https://shinrireviews.com/assets/cc0826_scarlet_bloom-WEGAaOjL.png",
    "cc0826_summer_begins": "https://shinrireviews.com/assets/cc0826_summer_begins-CO1lwML6.png",
    "cc0826_summer_tour": "https://shinrireviews.com/assets/cc0826_summer_tour-C2HJJ6un.png",
    "cc0826_tsumugi_vacation": "https://shinrireviews.com/assets/cc0826_tsumugi_vacation-D2PN3YhL.png",
    "cc0826_wild_beach": "https://shinrireviews.com/assets/cc0826_wild_beach-vKzwcJW_.png",
    "celestia_1": "https://shinrireviews.com/assets/celestia_1-Bj3I9gN0.png",
    "celestia_2-Dl-Fxtv9": "https://shinrireviews.com/assets/celestia_2-Dl-Fxtv9.png",
    "chiaki_1": "https://shinrireviews.com/assets/chiaki_1-ktmmfOPx.png",
    "chiaki_2": "https://shinrireviews.com/assets/chiaki_2-BPfhRgGt.png",
    "chiaki_chibi_1": "https://shinrireviews.com/assets/chiaki_chibi_1-NFbwZIWl.png",
    "chihiro_1": "https://shinrireviews.com/assets/chihiro_1-De3ox6j1.png",
    "chihiro_doubts": "https://shinrireviews.com/assets/chihiro_doubts-DTklG12E.png",
    "crester": "https://shinrireviews.com/assets/crester-DU0D_7xz.png",
    "cyberpunk_1": "https://shinrireviews.com/assets/cyberpunk_1-YxXOIRBa.png",
    "default": "https://shinrireviews.com/assets/default-LZMr4ZDr.png",
    "default_2": "https://shinrireviews.com/assets/default_2-DGnwv2UV.png",
    "dynasty": "https://shinrireviews.com/assets/dynasty-CQRryUbP.png",
    "edge_of_despair": "https://shinrireviews.com/assets/edge_of_despair-WF39YrQF.png",
    "epicbanner_1": "https://shinrireviews.com/assets/epicbanner_1-D5VHqLvg.png",
    "epicbanner_2-DNdz-5wk": "https://shinrireviews.com/assets/epicbanner_2-DNdz-5wk.png",
    "epicbanner_3": "https://shinrireviews.com/assets/epicbanner_3-5a04asIO.png",
    "epicframe_1": "https://shinrireviews.com/assets/epicframe_1-f4sbZ1x1.png",
    "epicframe_2": "https://shinrireviews.com/assets/epicframe_2-SMMWOcr4.png",
    "epicframe_3": "https://shinrireviews.com/assets/epicframe_3-BWn1EKfn.png",
    "fuyuhiko_1": "https://shinrireviews.com/assets/fuyuhiko_1-SMJDHBTC.png",
    "fuyuhiko_2": "https://shinrireviews.com/assets/fuyuhiko_2-BqoU8HPl.png",
    "fuyuhiko_3": "https://shinrireviews.com/assets/fuyuhiko_3-nnmQVpHR.png",
    "gonta_1": "https://shinrireviews.com/assets/gonta_1-BqH8hEyK.png",
    "gundham_1": "https://shinrireviews.com/assets/gundham_1-Ct8PqggV.png",
    "hajime_1": "https://shinrireviews.com/assets/hajime_1-6V8TIGHn.png",
    "hifumi_1": "https://shinrireviews.com/assets/hifumi_1-Dqs1uXy5.png",
    "himiko_1": "https://shinrireviews.com/assets/himiko_1-L8RAE_ZM.png",
    "hiyoko_1": "https://shinrireviews.com/assets/hiyoko_1-VJu6ByDw.png",
    "hiyoko_chibi_1": "https://shinrireviews.com/assets/hiyoko_chibi_1-DTt_Gp7Y.png",
    "ibuki_1": "https://shinrireviews.com/assets/ibuki_1-BigSyVZ9.png",
    "ibuki_2": "https://shinrireviews.com/assets/ibuki_2-utaZ8oAl.png",
    "jataro_1": "https://shinrireviews.com/assets/jataro_1-rftPlz0F.png",
    "junko_1": "https://shinrireviews.com/assets/junko_1-DUTpBojw.png",
    "junko_2-pfZ-7KRW": "https://shinrireviews.com/assets/junko_2-pfZ-7KRW.png",
    "junko_3": "https://shinrireviews.com/assets/junko_3-BzvtQqEx.png",
    "junko_4": "https://shinrireviews.com/assets/junko_4-CbOz0MSZ.png",
    "kaede_1": "https://shinrireviews.com/assets/kaede_1-CwPIXEJF.png",
    "kaede_2": "https://shinrireviews.com/assets/kaede_2-DFpkiaex.png",
    "kaguya_1": "https://shinrireviews.com/assets/kaguya_1-CyUPMRkr.png",
    "kaito_1": "https://shinrireviews.com/assets/kaito_1-BBUtfQES.png",
    "kaito_2": "https://shinrireviews.com/assets/kaito_2-D0yHFi6L.png",
    "kazuichi_1": "https://shinrireviews.com/assets/kazuichi_1-Bljc0Wx9.png",
    "kibo_1": "https://shinrireviews.com/assets/kibo_1-CC87syY9.png",
    "kibo_2": "https://shinrireviews.com/assets/kibo_2-CVAKToaf.png",
    "kirumi_1": "https://shinrireviews.com/assets/kirumi_1-r1sgMH1V.png",
    "kirumi_2-0n-dbsAK": "https://shinrireviews.com/assets/kirumi_2-0n-dbsAK.png",
    "kiyotaka_1": "https://shinrireviews.com/assets/kiyotaka_1-D8wuXJVz.png",
    "kiyotaka_dont_run": "https://shinrireviews.com/assets/kiyotaka_dont_run-BknTIFhA.png",
    "kokichi_1": "https://shinrireviews.com/assets/kokichi_1-qLvAhHMT.png",
    "kokichi_2": "https://shinrireviews.com/assets/kokichi_2-CdU3YOU_.png",
    "kokichi_3": "https://shinrireviews.com/assets/kokichi_3-DNzT8zGg.png",
    "kokichi_4": "https://shinrireviews.com/assets/kokichi_4-DADMRdwv.png",
    "komaru_1": "https://shinrireviews.com/assets/komaru_1-CjwGbI69.png",
    "korekiyo_1": "https://shinrireviews.com/assets/korekiyo_1-iIVGXvV8.png",
    "korekiyo_2": "https://shinrireviews.com/assets/korekiyo_2-nT6SzWxc.png",
    "kotoko_1": "https://shinrireviews.com/assets/kotoko_1-fhu6bKDA.png",
    "kyoko_1": "https://shinrireviews.com/assets/kyoko_1-Dr02MgDU.png",
    "kyoko_2": "https://shinrireviews.com/assets/kyoko_2-DYC9k8i4.png",
    "legbundle_1": "https://shinrireviews.com/assets/legbundle_1-iZf57JaI.png",
    "legbundle_2": "https://shinrireviews.com/assets/legbundle_2-bgS22AYn.png",
    "legbundle_3": "https://shinrireviews.com/assets/legbundle_3-auY85Tnm.png",
    "leon_1": "https://shinrireviews.com/assets/leon_1-A_cckxAE.png",
    "mahiru_1": "https://shinrireviews.com/assets/mahiru_1-vVWZg1As.png",
    "maki_1": "https://shinrireviews.com/assets/maki_1-CVGkkh6O.png",
    "maki_2": "https://shinrireviews.com/assets/maki_2-BDtNSlRr.png",
    "makoto_1": "https://shinrireviews.com/assets/makoto_1-DpQp9Ng1.png",
    "makoto_butler": "https://shinrireviews.com/assets/makoto_butler-CGR2v3pR.png",
    "masaru_1": "https://shinrireviews.com/assets/masaru_1-CtjPWD0l.png",
    "mikan_1": "https://shinrireviews.com/assets/mikan_1-z4rtvE5n.png",
    "mikan_2": "https://shinrireviews.com/assets/mikan_2-BiaErqgp.png",
    "mikan_chibi_1": "https://shinrireviews.com/assets/mikan_chibi_1-5yNh4VHr.png",
    "mikvoin": "https://shinrireviews.com/assets/mikvoin-CP28ig18.png",
    "miu_1": "https://shinrireviews.com/assets/miu_1-Det2nkxM.png",
    "miu_2": "https://shinrireviews.com/assets/miu_2-Bz7xt4V1.png",
    "miu_3": "https://shinrireviews.com/assets/miu_3-BGCZtErj.png",
    "monaca_1": "https://shinrireviews.com/assets/monaca_1-xTvun05a.png",
    "mondo_1": "https://shinrireviews.com/assets/mondo_1-ogVM0xm0.png",
    "monokuma_1": "https://shinrireviews.com/assets/monokuma_1-BeGTGV41.png",
    "mukuro_1": "https://shinrireviews.com/assets/mukuro_1-UwHK2ayU.png",
    "nagisa_1": "https://shinrireviews.com/assets/nagisa_1-SSEyekD2.png",
    "nagito_1": "https://shinrireviews.com/assets/nagito_1-DWqehYto.png",
    "nagito_2": "https://shinrireviews.com/assets/nagito_2-dBRQsQnj.png",
    "nekomaru_1": "https://shinrireviews.com/assets/nekomaru_1-CHo15kwq.png",
    "order": "https://shinrireviews.com/assets/order-Dr88yznq.png",
    "pb0826_clear_weather": "https://shinrireviews.com/assets/pb0826_clear_weather-gslF22Y7.png",
    "pb0826_hot_engine": "https://shinrireviews.com/assets/pb0826_hot_engine-DITW6EB9.png",
    "pb0826_mondo-o-dxQWH0": "https://shinrireviews.com/assets/pb0826_mondo-o-dxQWH0.png",
    "pb0826_monoshark-bo12_Ad-": "https://shinrireviews.com/assets/pb0826_monoshark-bo12_Ad-.png",
    "pb0826_summer_monokuma": "https://shinrireviews.com/assets/pb0826_summer_monokuma-CexXcDzR.png",
    "pb0826_summer_monomi": "https://shinrireviews.com/assets/pb0826_summer_monomi-D5JWUoo6.png",
    "peko_1": "https://shinrireviews.com/assets/peko_1-iO93N9Ou.png",
    "peko_2": "https://shinrireviews.com/assets/peko_2-CCZwmKKf.png",
    "rantaro_1": "https://shinrireviews.com/assets/rantaro_1-DziDashB.png",
    "rantaro_2": "https://shinrireviews.com/assets/rantaro_2-5qAiCex9.png",
    "rantaro_3": "https://shinrireviews.com/assets/rantaro_3-D_Q4EEbx.png",
    "rantaro_chibi_1": "https://shinrireviews.com/assets/rantaro_chibi_1-CPD_HTqU.png",
    "ryoko_1-B-T7l3nz": "https://shinrireviews.com/assets/ryoko_1-B-T7l3nz.png",
    "ryoma_1": "https://shinrireviews.com/assets/ryoma_1-ClZO1enW.png",
    "sakura_1": "https://shinrireviews.com/assets/sakura_1-CZwWTlOs.png",
    "sayaka_1": "https://shinrireviews.com/assets/sayaka_1-Ccu1pWpv.png",
    "sayaka_idol_love-Ctl1a-JS": "https://shinrireviews.com/assets/sayaka_idol_love-Ctl1a-JS.png",
    "semyon": "https://shinrireviews.com/assets/semyon-5Bmj1BeR.png",
    "shark": "https://shinrireviews.com/assets/shark-D3hSrn66.png",
    "shuichi_1": "https://shinrireviews.com/assets/shuichi_1-C5kAtCZC.png",
    "shuichi_2": "https://shinrireviews.com/assets/shuichi_2-BC0vb_42.png",
    "shuichi_3": "https://shinrireviews.com/assets/shuichi_3-DiVCF9s6.png",
    "sonia_1": "https://shinrireviews.com/assets/sonia_1-Dah187wh.png",
    "tanibata26-XJb-w60n": "https://shinrireviews.com/assets/tanibata26-XJb-w60n.png",
    "tea_party": "https://shinrireviews.com/assets/tea_party-D3Kd56uE.png",
    "tenko_1": "https://shinrireviews.com/assets/tenko_1-7Hjix0Xc.png",
    "teruteru_1-CP27J-NQ": "https://shinrireviews.com/assets/teruteru_1-CP27J-NQ.png",
    "teruteru_2": "https://shinrireviews.com/assets/teruteru_2-CR8lLk4R.png",
    "toko_1": "https://shinrireviews.com/assets/toko_1-Dna0DMe_.png",
    "toko_2-D67P_NP-": "https://shinrireviews.com/assets/toko_2-D67P_NP-.png",
    "toko_3": "https://shinrireviews.com/assets/toko_3-COyrznSD.png",
    "totems": "https://shinrireviews.com/assets/totems-BT_5p3eV.png",
    "tsumugi_1": "https://shinrireviews.com/assets/tsumugi_1-CIkV0qSX.png",
    "vrnfest26": "https://shinrireviews.com/assets/vrnfest26-CQuY6tOw.png",
    "yasuhiro_1-CxYF-nYD": "https://shinrireviews.com/assets/yasuhiro_1-CxYF-nYD.png",
    "zazacat": "https://shinrireviews.com/assets/zazacat-CQ9iu4ZC.png",
}

DEFAULT_AVATAR_URL = "https://shinrireviews.com/assets/default-LZMr4ZDr.png"


class ShinriError(Exception):
    pass


class ShinriNetworkError(ShinriError):
    pass


class ShinriClient:
    BASE_URL = "https://shinrireviews.com"
    API_URL = "https://shinrireviews.com/rapi"
    DEFAULT_CACHE_FILE = "shinri_ratings_cache.json"

    def __init__(
        self,
        cache_path: Optional[str] = None,
        cache_ttl_seconds: int = 3600,
        offline_mode: bool = False,
        timeout: int = 15,
        delay_between_requests: float = 0.15,
    ):
        self.cache_path = cache_path or self.DEFAULT_CACHE_FILE
        self.cache_ttl_seconds = cache_ttl_seconds
        self.offline_mode = offline_mode
        self.timeout = timeout
        self.delay_between_requests = delay_between_requests
        self.last_request_time = 0.0

        # Memory indexes
        self._ratings: List[Dict[str, Any]] = []
        self._by_id: Dict[int, Dict[str, Any]] = {}
        self._by_name_exact: Dict[str, List[Dict[str, Any]]] = {}
        self._by_name_lower: Dict[str, List[Dict[str, Any]]] = {}
        self._loaded_at: Optional[float] = None
        self._data_source: str = "none"
        self._global_avg_rating: float = 4.80  # Baseline prior for Bayesian formula
        self._reviews_detail_cache: Dict[int, Dict[str, Any]] = {}
        self._sorted_names_by_length: List[str] = []

        # Session lookups and negative caching to eliminate redundant network queries
        self._online_name_cache: Dict[str, Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]] = {}
        self._online_id_cache: Dict[int, Optional[Dict[str, Any]]] = {}
        self._negative_name_cache: Set[str] = set()
        self._negative_id_cache: Set[int] = set()

        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://shinrireviews.com/",
            "Origin": "https://shinrireviews.com",
        }

    @property
    def is_loaded(self) -> bool:
        return len(self._ratings) > 0

    @property
    def data_source(self) -> str:
        return self._data_source

    @property
    def total_rated_players(self) -> int:
        return len(self._ratings)

    @property
    def global_avg_rating(self) -> float:
        return self._global_avg_rating

    @classmethod
    def get_avatar_url(cls, avatar_game_id: Optional[str]) -> str:
        """Returns direct live image URL for a DRO character avatar."""
        if not avatar_game_id:
            return DEFAULT_AVATAR_URL
        clean_id = avatar_game_id.strip().lower()
        return AVATAR_CDN_MAP.get(clean_id, DEFAULT_AVATAR_URL)

    def _throttle(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay_between_requests:
            time.sleep(self.delay_between_requests - elapsed)
        self.last_request_time = time.time()

    def _http_get_json(self, url: str, max_retries: int = 3) -> Any:
        if self.offline_mode:
            raise ShinriNetworkError(
                f"Клиент находится в автономном (оффлайн) режиме. Сетевой запрос к {url} отклонен."
            )

        self._throttle()
        attempt = 0
        last_err = None

        while attempt < max_retries:
            attempt += 1
            try:
                req = urllib.request.Request(url, headers=self._headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 204:
                        return None
                    data = resp.read().decode("utf-8", errors="replace")
                    if not data.strip():
                        return None
                    return json.loads(data)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                last_err = e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e

            if attempt < max_retries:
                time.sleep(0.8 * (2 ** (attempt - 1)))

        raise ShinriNetworkError(
            f"Не удалось подключиться к shinrireviews.com после {max_retries} попыток. "
            f"Причина: {last_err}."
        )

    def load_ratings(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        now = time.time()

        if not force_refresh and self._ratings and self._loaded_at:
            if (now - self._loaded_at) < self.cache_ttl_seconds:
                return self._ratings

        cached_data = self._read_cache_file()
        if cached_data is not None:
            cached_time = cached_data.get("timestamp", 0)
            if not force_refresh and (self.offline_mode or (now - cached_time) < self.cache_ttl_seconds):
                self._populate_indexes(cached_data.get("ratings", []))
                self._loaded_at = cached_time
                self._data_source = "cache"
                return self._ratings
            elif not self.is_loaded:
                # Instantly warm up memory indexes from existing cache to prevent startup freeze
                self._populate_indexes(cached_data.get("ratings", []))
                self._loaded_at = cached_time
                self._data_source = "cache"

        if self.offline_mode:
            raise ShinriNetworkError(
                "Автономный режим активен, но локальный кэш не найден. "
                "Импортируйте файл базы данных или отключите оффлайн-режим."
            )

        try:
            logger.info("Загрузка актуального рейтинга игроков с %s/ratings...", self.API_URL)
            data = self._http_get_json(f"{self.API_URL}/ratings")
            if not isinstance(data, list):
                raise ShinriNetworkError(f"Неожиданный формат ответа от /ratings: {type(data)}")

            # Also fetch and merge all registered players from /rapi/players (~50k registered DRO players)
            try:
                players_data = self._http_get_json(f"{self.API_URL}/players")
                if isinstance(players_data, list):
                    rated_ids = {int(r.get("playerId", 0)) for r in data}
                    for item in players_data:
                        if isinstance(item, list) and len(item) >= 2:
                            pid = int(item[0])
                            if pid not in rated_ids:
                                pname = str(item[1]).strip()
                                avatar = str(item[4]).strip() if len(item) > 4 and item[4] else None
                                data.append({
                                    "playerId": pid,
                                    "playerName": pname,
                                    "avg": 0.0,
                                    "count": 0,
                                    "avatarGameId": avatar,
                                })
                                rated_ids.add(pid)
            except Exception as e:
                logger.warning("Не удалось объединить /players при обновлении: %s", e)

            self._populate_indexes(data)
            self._loaded_at = now
            self._data_source = "network"
            self._write_cache_file(data)
            return self._ratings

        except ShinriNetworkError as e:
            logger.warning("Сетевой запрос не удался (%s). Попытка использовать резервный кэш...", e)
            cached_data = self._read_cache_file()
            if cached_data is not None:
                self._populate_indexes(cached_data.get("ratings", []))
                self._loaded_at = cached_data.get("timestamp", now)
                self._data_source = "fallback_cache"
                return self._ratings
            raise

    def _populate_indexes(self, ratings_list: List[Dict[str, Any]]) -> None:
        self._ratings = ratings_list
        self._by_id.clear()
        self._by_name_exact.clear()
        self._by_name_lower.clear()

        total_score = 0.0
        valid_scores_count = 0

        for r in ratings_list:
            pid = int(r.get("playerId", 0))
            name = str(r.get("playerName", "")).strip()
            avatar_id = r.get("avatarGameId")
            avg_score = float(r.get("avg", 0.0))

            if avg_score > 0:
                total_score += avg_score
                valid_scores_count += 1

            record = {
                "id": pid,
                "name": name,
                "avg": avg_score,
                "count": int(r.get("count", 0)),
                "last": r.get("last"),
                "avatarGameId": avatar_id,
                "avatar_url": self.get_avatar_url(avatar_id),
                "profile_url": f"{self.BASE_URL}/p/{pid}",
            }

            self._by_id[pid] = record

            if name:
                self._by_name_exact.setdefault(name, []).append(record)
                self._by_name_lower.setdefault(name.lower(), []).append(record)

        if valid_scores_count > 0:
            self._global_avg_rating = round(total_score / valid_scores_count, 3)

        self._sorted_names_by_length = sorted(self._by_name_lower.keys(), key=lambda x: -len(x))

    def _read_cache_file(self) -> Optional[Dict[str, Any]]:
        candidates = [self.cache_path]
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            candidates.insert(0, os.path.join(exe_dir, os.path.basename(self.cache_path)))
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(os.path.join(meipass, os.path.basename(self.cache_path)))

        for p in candidates:
            # Ultra-fast path: read pre-compiled binary cache if available and up-to-date
            p_bin = p + ".dat"
            if os.path.exists(p_bin) and os.path.exists(p):
                try:
                    if os.path.getmtime(p_bin) >= os.path.getmtime(p):
                        with open(p_bin, "rb") as bf:
                            return marshal.load(bf)
                except Exception:
                    pass

            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Automatically generate binary cache for instant subsequent launches
                    try:
                        with open(p_bin, "wb") as bf:
                            marshal.dump(data, bf)
                    except Exception:
                        pass
                    return data
                except Exception:
                    continue
        return None

    def _write_cache_file(self, ratings: List[Dict[str, Any]]) -> None:
        target_path = self.cache_path
        if getattr(sys, "frozen", False) and target_path == self.DEFAULT_CACHE_FILE:
            target_path = os.path.join(os.path.dirname(sys.executable), self.DEFAULT_CACHE_FILE)
        try:
            cache_obj = {
                "timestamp": time.time(),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": self.BASE_URL,
                "count": len(ratings),
                "ratings": ratings,
            }
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(cache_obj, f, ensure_ascii=False, indent=2)
            try:
                with open(target_path + ".dat", "wb") as bf:
                    marshal.dump(cache_obj, bf)
            except Exception:
                pass
        except Exception:
            pass

    def export_cache(self, output_path: str) -> None:
        if not self._ratings:
            self.load_ratings()
        data = {
            "timestamp": time.time(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": self.BASE_URL,
            "count": len(self._ratings),
            "ratings": self._ratings,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_cache(self, input_path: str) -> int:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ratings = data.get("ratings") if isinstance(data, dict) else data
        if not isinstance(ratings, list):
            raise ValueError("Некорректный формат: ожидается список игроков или объект с 'ratings'")
        self._populate_indexes(ratings)
        self._loaded_at = time.time()
        self._data_source = "imported_file"
        self._write_cache_file(ratings)
        return len(ratings)

    # ---------------- Lookups ----------------

    def find_by_id(self, player_id: int) -> Optional[Dict[str, Any]]:
        if not self._ratings:
            self.load_ratings()
        return self._by_id.get(player_id)

    def find_by_name(self, name: str) -> List[Dict[str, Any]]:
        if not self._ratings:
            self.load_ratings()

        name = name.strip()
        if name in self._by_name_exact:
            return self._by_name_exact[name]

        name_lower = name.lower()
        if name_lower in self._by_name_lower:
            return self._by_name_lower[name_lower]

        return []

    def fetch_player_online_by_id(self, player_id: int) -> Optional[Dict[str, Any]]:
        if self.offline_mode or player_id in self._negative_id_cache:
            return None

        if player_id in self._online_id_cache:
            return self._online_id_cache[player_id]

        player_data = self._http_get_json(f"{self.API_URL}/players/{player_id}")
        if not player_data:
            self._negative_id_cache.add(player_id)
            return None

        stats = {"count": 0, "avg": 0.0}
        try:
            reviews_data = self._http_get_json(f"{self.API_URL}/reviews/{player_id}")
            if reviews_data and isinstance(reviews_data, dict):
                s = reviews_data.get("stats")
                if s:
                    stats["count"] = int(s.get("count", 0))
                    stats["avg"] = float(s.get("avg", 0.0))
        except Exception:
            pass

        avatar_id = player_data.get("avatarGameId")
        res = {
            "id": int(player_data.get("id", player_id)),
            "name": str(player_data.get("name", "")).strip(),
            "avg": stats["avg"],
            "count": stats["count"],
            "avatarGameId": avatar_id,
            "avatar_url": self.get_avatar_url(avatar_id),
            "profile_url": f"{self.BASE_URL}/p/{player_id}",
            "is_unrated": stats["count"] == 0,
        }
        self._online_id_cache[player_id] = res
        return res

    def fetch_player_online_by_name(self, name: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        if self.offline_mode:
            return None, []

        name = name.strip()
        name_lower = name.lower()
        if name_lower in self._negative_name_cache:
            return None, []

        if name_lower in self._online_name_cache:
            return self._online_name_cache[name_lower]

        quoted_name = urllib.parse.quote(name)

        # 1. Try exact by-name
        try:
            player_data = self._http_get_json(f"{self.API_URL}/players/by-name?name={quoted_name}")
            if player_data and isinstance(player_data, dict):
                pid = int(player_data.get("id"))
                stats = {"count": 0, "avg": 0.0}
                reviews_data = self._http_get_json(f"{self.API_URL}/reviews/{pid}")
                if reviews_data and isinstance(reviews_data, dict):
                    s = reviews_data.get("stats")
                    if s:
                        stats["count"] = int(s.get("count", 0))
                        stats["avg"] = float(s.get("avg", 0.0))

                avatar_id = player_data.get("avatarGameId")
                res = {
                    "id": pid,
                    "name": str(player_data.get("name", "")).strip(),
                    "avg": stats["avg"],
                    "count": stats["count"],
                    "avatarGameId": avatar_id,
                    "avatar_url": self.get_avatar_url(avatar_id),
                    "profile_url": f"{self.BASE_URL}/p/{pid}",
                    "is_unrated": stats["count"] == 0,
                }
                self._online_name_cache[name_lower] = (res, [])
                self._online_id_cache[pid] = res
                return res, []
        except Exception:
            pass

        # 2. Try search endpoint
        try:
            search_res = self._http_get_json(f"{self.API_URL}/players/search?q={quoted_name}")
            if search_res and isinstance(search_res, dict):
                items = search_res.get("items", [])
                candidates = []
                for item in items:
                    rating = item.get("rating")
                    avatar_id = item.get("avatarGameId")
                    cand = {
                        "id": int(item.get("id")),
                        "name": str(item.get("name", "")).strip(),
                        "avg": float(rating.get("avg", 0.0)) if rating else 0.0,
                        "count": int(rating.get("count", 0)) if rating else 0,
                        "avatarGameId": avatar_id,
                        "avatar_url": self.get_avatar_url(avatar_id),
                        "profile_url": f"{self.BASE_URL}/p/{item.get('id')}",
                        "is_unrated": not rating or int(rating.get("count", 0)) == 0,
                    }
                    candidates.append(cand)

                for c in candidates:
                    if c["name"].lower() == name_lower:
                        self._online_name_cache[name_lower] = (c, candidates)
                        self._online_id_cache[c["id"]] = c
                        return c, candidates

                if candidates:
                    self._online_name_cache[name_lower] = (None, candidates)
                    return None, candidates
        except Exception:
            pass

        self._negative_name_cache.add(name_lower)
        return None, []

    def fetch_player_nick_history(self, player_id: int) -> Dict[str, Any]:
        """Fetch nick history for a player: {'current': '...', 'history': [...]}"""
        if self.offline_mode:
            return {"current": "", "history": []}
        try:
            data = self._http_get_json(f"{self.API_URL}/players/{player_id}/nick-history")
            return data if isinstance(data, dict) else {"current": "", "history": []}
        except Exception:
            return {"current": "", "history": []}

    def fetch_player_detailed_reviews(self, player_id: int) -> Dict[str, Any]:
        """
        Deep review analysis:
        - Calculates verified_avg & verified_count
        - Finds top liked review quote
        - Extracts prominent sentiment words
        """
        if player_id in self._reviews_detail_cache:
            return self._reviews_detail_cache[player_id]

        if self.offline_mode:
            return {
                "verified_avg": None,
                "verified_count": 0,
                "top_review": None,
                "latest_review": None,
                "tags": [],
            }

        try:
            data = self._http_get_json(f"{self.API_URL}/reviews/{player_id}")
            if not data or not isinstance(data, dict):
                return {}

            reviews = data.get("reviews", [])
            if not isinstance(reviews, list) or not reviews:
                res = {
                    "verified_avg": None,
                    "verified_count": 0,
                    "top_review": None,
                    "latest_review": None,
                    "tags": [],
                }
                self._reviews_detail_cache[player_id] = res
                return res

            verified_scores = []
            top_rev = None
            max_likes = -1
            latest_rev = None

            word_freq: Dict[str, int] = {}
            stop_words = {"и", "в", "не", "на", "я", "с", "что", "а", "он", "по", "но", "как", "то", "все", "он", "его", "от", "за", "да", "ну", "это", "же"}

            for r in reviews:
                score = float(r.get("rating", 0))
                is_verified = bool(r.get("authorVerified", False))
                if is_verified and score > 0:
                    verified_scores.append(score)

                likes = int(r.get("likes", 0))
                text = str(r.get("text", "")).strip()

                if text:
                    if likes > max_likes:
                        max_likes = likes
                        top_rev = {
                            "text": text,
                            "rating": score,
                            "likes": likes,
                            "author": r.get("authorNickname") or r.get("authorGameName") or "Аноним",
                            "verified": is_verified,
                        }

                    if latest_rev is None:
                        latest_rev = {
                            "text": text,
                            "rating": score,
                            "author": r.get("authorNickname") or r.get("authorGameName") or "Аноним",
                        }

                    # Extract keywords
                    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ]{4,}", text.lower())
                    for w in words:
                        if w not in stop_words:
                            word_freq[w] = word_freq.get(w, 0) + 1

            verified_avg = round(sum(verified_scores) / len(verified_scores), 2) if verified_scores else None

            # Sort top tags & analyze sentiment
            sorted_tags = sorted(word_freq.items(), key=lambda x: -x[1])[:6]
            tags = [t[0] for t in sorted_tags if t[1] >= 2]

            sentiment_info = {}
            try:
                from .analytics import SentimentAnalyzer
                sentiment_info = SentimentAnalyzer.analyze_reviews(reviews)
                if sentiment_info.get("tags"):
                    tags = list(dict.fromkeys(tags + sentiment_info["tags"]))[:8]
            except Exception:
                pass

            res = {
                "verified_avg": verified_avg,
                "verified_count": len(verified_scores),
                "top_review": top_rev,
                "latest_review": latest_rev,
                "tags": tags,
                "sentiment": sentiment_info.get("sentiment", "neutral"),
                "sentiment_label": sentiment_info.get("label", "Нейтральная"),
                "polarity": sentiment_info.get("polarity", 0.0),
            }
            self._reviews_detail_cache[player_id] = res
            return res

        except Exception as e:
            logger.warning("Ошибка получения деталей отзывов для игрока %d: %s", player_id, e)
            return {}

    def refresh_delta(self, force_full: bool = False) -> Dict[str, Any]:
        """
        Smart delta sync:
        Compares live ratings with local cache, identifies changes (added, updated, unchanged),
        updates in-memory structures, and saves the new cache file.
        """
        start_time = time.time()
        if self.offline_mode:
            return {
                "status": "offline",
                "message": "Клиент работает в оффлайн-режиме, синхронизация с сетью отключена.",
                "total": len(self._ratings),
            }

        data = self._http_get_json(f"{self.API_URL}/ratings")
        if not isinstance(data, list):
            raise ShinriNetworkError(f"Неожиданный формат ответа от /ratings: {type(data)}")

        old_map = {int(r.get("playerId", 0)): r for r in self._ratings}
        added_count = 0
        updated_count = 0
        unchanged_count = 0

        for r in data:
            pid = int(r.get("playerId", 0))
            if pid not in old_map:
                added_count += 1
            else:
                old_r = old_map[pid]
                if old_r.get("count") != r.get("count") or old_r.get("avg") != r.get("avg"):
                    updated_count += 1
                else:
                    unchanged_count += 1

        self._populate_indexes(data)
        self._loaded_at = time.time()
        self._data_source = "network_delta"
        self._write_cache_file(data)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "status": "ok",
            "added": added_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "total": len(data),
            "delta_time_ms": elapsed_ms,
        }
