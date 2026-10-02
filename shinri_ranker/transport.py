"""Bounded, thread-safe HTTP connection reuse, retaining environment proxy support."""

from __future__ import annotations
import threading
import ssl
import urllib.error
import urllib.parse
import urllib.request

import urllib3


class JsonTransport:
    def __init__(self):
        self._lock = threading.Lock()
        self._direct = urllib3.PoolManager(
            num_pools=4, maxsize=8, block=True, cert_reqs=ssl.CERT_REQUIRED
        )
        self._proxies = {}
        self._environment = urllib.request.getproxies()

    def _manager(self, url):
        parsed = urllib.parse.urlsplit(url)
        proxy = self._environment.get(parsed.scheme)
        if not proxy or urllib.request.proxy_bypass(parsed.hostname):
            return self._direct
        with self._lock:
            if proxy not in self._proxies:
                proxy_url = urllib.parse.urlsplit(proxy)
                headers = None
                if proxy_url.username is not None:
                    auth = f"{urllib.parse.unquote(proxy_url.username)}:{urllib.parse.unquote(proxy_url.password or '')}"
                    headers = urllib3.make_headers(proxy_basic_auth=auth)
                self._proxies[proxy] = urllib3.ProxyManager(
                    proxy,
                    proxy_headers=headers,
                    cert_reqs=ssl.CERT_REQUIRED,
                    num_pools=4,
                    maxsize=8,
                    block=True,
                )
            return self._proxies[proxy]

    def get(self, url, headers, remaining):
        origin = urllib.parse.urlsplit(url)
        if origin.scheme not in ("http", "https") or not origin.hostname or origin.username:
            raise urllib.error.URLError("Некорректный адрес API")
        for _ in range(4):
            budget = remaining()
            try:
                response = self._manager(url).request(
                    "GET",
                    url,
                    headers=headers,
                    retries=False,
                    redirect=False,
                    timeout=urllib3.Timeout(total=budget),
                    pool_timeout=budget,
                )
            except urllib3.exceptions.HTTPError as exc:
                raise urllib.error.URLError("Сетевое соединение API прервано") from exc
            try:
                status, body = response.status, response.data
                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    target = urllib.parse.urljoin(url, location or "")
                    parsed = urllib.parse.urlsplit(target)
                    if (
                        not location
                        or (parsed.scheme, parsed.hostname, parsed.port)
                        != (origin.scheme, origin.hostname, origin.port)
                        or parsed.username
                    ):
                        raise urllib.error.URLError("API перенаправил запрос на другой адрес")
                    url = target
                    continue
                if status >= 400:
                    raise urllib.error.HTTPError(url, status, "API error", response.headers, None)
                if status >= 300:
                    raise urllib.error.URLError("Неожиданный ответ API")
                return status, body
            finally:
                response.release_conn()
        raise urllib.error.URLError("Слишком много перенаправлений API")

    def close(self):
        with self._lock:
            self._direct.clear()
            for manager in self._proxies.values():
                manager.clear()
            self._proxies.clear()
