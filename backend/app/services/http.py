"""Polite HTTP fetching: robots.txt, per-host throttling, retries."""

import logging
import time
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.redis_client import get_redis

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


class BlockedByRobots(FetchError):
    pass


class Fetcher:
    def __init__(self, delay: float | None = None):
        self.delay = settings.crawler_delay_seconds if delay is None else delay
        self.client = httpx.Client(
            headers={
                "User-Agent": settings.crawler_user_agent,
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=settings.crawler_timeout_seconds,
            follow_redirects=True,
        )
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._local_next: dict[str, float] = {}

    # -- robots ------------------------------------------------------------
    def allowed(self, url: str) -> bool:
        if not settings.crawler_respect_robots:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.client.get(f"{base}/robots.txt", timeout=10)
                if resp.status_code >= 400:
                    rp = None  # no robots.txt → everything allowed
                else:
                    rp.parse(resp.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(settings.crawler_user_agent, url)

    # -- throttle ----------------------------------------------------------
    def _throttle(self, host: str) -> None:
        if self.delay <= 0:
            return
        now = time.time()
        try:
            r = get_redis()
            key = f"crawl:next:{host}"
            nxt = float(r.get(key) or 0)
            wait = max(0.0, nxt - now)
            r.set(key, max(now, nxt) + self.delay, ex=int(self.delay * 10) + 60)
        except Exception:  # redis down → per-process throttle
            nxt = self._local_next.get(host, 0)
            wait = max(0.0, nxt - now)
            self._local_next[host] = max(now, nxt) + self.delay
        if wait:
            time.sleep(min(wait, 60))

    # -- fetch -------------------------------------------------------------
    def get(self, url: str, *, params: dict | None = None, check_robots: bool = True, retries: int = 2) -> httpx.Response:
        if check_robots and not self.allowed(url):
            raise BlockedByRobots(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._throttle(host)
            try:
                resp = self.client.get(url, params=params)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** (attempt + 1) * 2)
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} for {url}")
                return resp
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(2 ** (attempt + 1))
        raise FetchError(f"Failed to fetch {url}: {last_exc}")

    def close(self) -> None:
        self.client.close()


_fetcher: Fetcher | None = None


def get_fetcher() -> Fetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = Fetcher()
    return _fetcher
