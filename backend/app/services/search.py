"""Web search and news feeds via official APIs / public RSS (no SERP scraping)."""

import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

import feedparser

from app.config import settings
from app.services.extraction import parse_date
from app.services.http import Fetcher

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: datetime | None = None
    source: str = ""


class SearchProvider:
    name = "none"

    def search(self, query: str, num: int = 10, recency_days: int | None = None) -> list[SearchResult]:
        return []


class SerpApiProvider(SearchProvider):
    name = "serpapi"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    def search(self, query, num=10, recency_days=None):
        params = {"engine": "google", "q": query, "gl": "in", "hl": "en", "num": num, "api_key": settings.serpapi_key}
        if recency_days:
            params["tbs"] = f"qdr:d{recency_days}" if recency_days < 365 else "qdr:y"
        data = self.fetcher.get("https://serpapi.com/search.json", params=params, check_robots=False).json()
        out = []
        for r in data.get("organic_results", [])[:num]:
            out.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                    published_at=parse_date(r.get("date")),
                    source="serpapi",
                )
            )
        return [r for r in out if r.url]


class GoogleCSEProvider(SearchProvider):
    name = "google_cse"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    def search(self, query, num=10, recency_days=None):
        params = {"key": settings.google_cse_key, "cx": settings.google_cse_cx, "q": query, "num": min(num, 10), "gl": "in"}
        if recency_days:
            params["dateRestrict"] = f"d{recency_days}"
        data = self.fetcher.get("https://www.googleapis.com/customsearch/v1", params=params, check_robots=False).json()
        return [
            SearchResult(title=i.get("title", ""), url=i.get("link", ""), snippet=i.get("snippet", ""), source="google_cse")
            for i in data.get("items", [])
            if i.get("link")
        ]


def get_search_provider(fetcher: Fetcher) -> SearchProvider:
    if settings.search_provider == "serpapi" and settings.serpapi_key:
        return SerpApiProvider(fetcher)
    if settings.search_provider == "google_cse" and settings.google_cse_key and settings.google_cse_cx:
        return GoogleCSEProvider(fetcher)
    return SearchProvider()


# ----------------------------------------------------------------- news RSS


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"


def fetch_rss(fetcher: Fetcher, feed_url: str, limit: int = 30) -> list[SearchResult]:
    resp = fetcher.get(feed_url, check_robots=False)
    feed = feedparser.parse(resp.content)
    out = []
    for e in feed.entries[:limit]:
        link = e.get("link", "")
        summary = e.get("summary", "") or ""
        if "<" in summary:
            from bs4 import BeautifulSoup

            summary = BeautifulSoup(summary, "lxml").get_text(" ", strip=True)
        src = e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else ""
        out.append(
            SearchResult(
                title=e.get("title", ""),
                url=link,
                snippet=summary[:1000],
                published_at=parse_date(e.get("published") or e.get("updated")),
                source=src or "rss",
            )
        )
    return [r for r in out if r.url]
