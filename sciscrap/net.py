"""HTTP plumbing: per-thread sessions with retries, and a per-host rate limiter."""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT, Config


class CappedRetry(Retry):
    """Honours Retry-After, but never sleeps longer than MAX_WAIT (some APIs ask for minutes)."""

    MAX_WAIT = 20.0

    def get_retry_after(self, response):
        value = super().get_retry_after(response)
        return None if value is None else min(value, self.MAX_WAIT)


class HostRateLimiter:
    """Guarantees at least `delay` seconds between request starts to the same host."""

    def __init__(self, delay: float):
        self.delay = delay
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}

    def wait(self, url: str) -> None:
        if self.delay <= 0:
            return
        host = urlparse(url).netloc.lower()
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + self.delay
        sleep_for = slot - now
        if sleep_for > 0:
            time.sleep(sleep_for)


class Http:
    def __init__(self, config: Config):
        self.config = config
        self.limiter = HostRateLimiter(config.delay)
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            retry = CappedRetry(
                total=3,
                connect=1,  # dead hosts/mirrors: fail fast, the caller moves on
                read=2,
                backoff_factor=2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET", "HEAD"),
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
            if self.config.proxy:
                session.proxies.update({"http": self.config.proxy, "https": self.config.proxy})
            self._local.session = session
        return session

    def get(self, url: str, *, polite: bool = True, **kwargs) -> requests.Response:
        if polite:
            self.limiter.wait(url)
        kwargs.setdefault("timeout", self.config.timeout)
        return self._session().get(url, **kwargs)

    def get_json(self, url: str, **kwargs) -> dict:
        resp = self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()
