"""Collectors for each source kind.

news_rss      config: {"query": "..."} (Google News RSS) or Source.url = any RSS/Atom feed
search        config: {"query": "...", "recency_days": 30, "num": 10}  (needs SerpAPI / Google CSE)
listing       Source.url = HTML page listing notices/news (e.g. RIICO); config: {"link_keywords": [...], "max_links": 40}
tender_table  Source.url = GePNIC/CPPP style table of tenders; config: {"keywords": [...]} (rows are pre-filtered)
"""

import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.models import Source, SourceKind
from app.services.collectors import RawItem
from app.services.extraction import LOCATION_TERMS, PROJECT_TERMS, clean_text, parse_date, sha256
from app.services.http import Fetcher
from app.services.search import fetch_rss, get_search_provider, google_news_url

log = logging.getLogger(__name__)

DEFAULT_LISTING_KEYWORDS = [
    "tender", "nit", "notice", "allot", "allotment", "auction", "plot", "industrial area", "construction",
    "development", "civil", "road", "building", "bhiwadi", "neemrana", "tapukara", "khushkhera", "expansion",
]
_DATE_RE = re.compile(r"\b(\d{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3})[-/.]\d{2,4}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?)", re.I)


def collect(source: Source, fetcher: Fetcher) -> list[RawItem]:
    kind = source.kind
    if kind == SourceKind.NEWS_RSS:
        return collect_news(source, fetcher)
    if kind == SourceKind.SEARCH:
        return collect_search(source, fetcher)
    if kind == SourceKind.LISTING:
        return collect_listing(source, fetcher)
    if kind == SourceKind.TENDER_TABLE:
        return collect_tender_table(source, fetcher)
    raise ValueError(f"Unsupported source kind: {kind}")


def collect_news(source: Source, fetcher: Fetcher) -> list[RawItem]:
    cfg = source.config or {}
    feed_url = source.url or google_news_url(cfg["query"])
    return [
        RawItem(url=r.url, title=r.title, snippet=r.snippet, published_at=r.published_at, meta={"publisher": r.source})
        for r in fetch_rss(fetcher, feed_url, limit=int(cfg.get("limit", 30)))
    ]


def collect_search(source: Source, fetcher: Fetcher) -> list[RawItem]:
    cfg = source.config or {}
    provider = get_search_provider(fetcher)
    if provider.name == "none":
        raise RuntimeError("No search provider configured (set SEARCH_PROVIDER + API key)")
    results = provider.search(cfg["query"], num=int(cfg.get("num", 10)), recency_days=cfg.get("recency_days", 60))
    return [RawItem(url=r.url, title=r.title, snippet=r.snippet, published_at=r.published_at) for r in results]


def collect_listing(source: Source, fetcher: Fetcher) -> list[RawItem]:
    cfg = source.config or {}
    keywords = [k.lower() for k in cfg.get("link_keywords", DEFAULT_LISTING_KEYWORDS)]
    resp = fetcher.get(source.url)
    soup = BeautifulSoup(resp.text, "lxml")
    base_host = urlsplit(str(resp.url)).netloc
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(str(resp.url), href)
        is_doc = url.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"))
        if cfg.get("only_documents") and not is_doc:
            continue  # skip navigation menus on portals whose notices are all PDFs
        context = _link_context(a, text)
        if len(text) < 15 or text.lower().startswith(("view more", "read more", "click here", "download")):
            text = context  # generic anchor text: the surrounding row is the real title
        if len(text) < 15 or len(context) > 3000:
            continue
        blob = f"{text} {context}".lower()
        if not any(k in blob for k in keywords):
            continue
        if url in seen:
            continue
        seen.add(url)
        m = _DATE_RE.search(context)
        items.append(
            RawItem(
                url=url,
                title=text[:300],
                snippet=context[:1500],
                content_text=context if is_doc or urlsplit(url).netloc != base_host else None,
                published_at=parse_date(m.group(1)) if m else None,
                meta={"listing": source.url, "is_document": is_doc},
            )
        )
        if len(items) >= int(cfg.get("max_links", 40)):
            break
    return items


def _link_context(a, anchor_text: str) -> str:
    """Nearest ancestor text describing a link — dates and titles usually sit next to it."""
    node = a
    for _ in range(5):
        node = node.parent
        if node is None or node.name in ("body", "html"):
            break
        if len({x.get("href") for x in node.find_all("a", href=True)}) > 1:
            break  # reached a container shared with other links (a menu or the whole list)
        text = clean_text(node.get_text(" ", strip=True))
        if len(text) > 1500:
            break
        if len(text) >= max(25, len(anchor_text) + 10):
            return text
    return anchor_text


def collect_tender_table(source: Source, fetcher: Fetcher) -> list[RawItem]:
    """Parse public 'latest active tenders' tables. Rows are kept only if they mention both
    construction-type work and a target location — the portal lists tenders state/nation-wide."""
    cfg = source.config or {}
    work_terms = [k.lower() for k in cfg.get("keywords", [])] or PROJECT_TERMS + [
        "work", "works", "repair", "renovation", "shed", "warehouse", "godown", "boundary", "drain", "road",
    ]
    loc_terms = [k.lower() for k in cfg.get("locations", [])] or LOCATION_TERMS
    resp = fetcher.get(source.url)
    soup = BeautifulSoup(resp.text, "lxml")
    items = []
    for tr in soup.find_all("tr"):
        if tr.find("table"):
            continue  # layout row wrapping a nested table
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(cells) < 3:
            continue
        row = " | ".join(c for c in cells if c)
        low = row.lower()
        if not any(t in low for t in loc_terms) or not any(t in low for t in work_terms):
            continue
        link = tr.find("a", href=True)
        href = urljoin(str(resp.url), link["href"]) if link else None
        # GePNIC links carry a per-session token, so they are not stable identifiers.
        url = href if href and "session=" not in href else _row_url(source.url, row)
        dates = _DATE_RE.findall(row)
        items.append(
            RawItem(
                url=url,
                title=(link.get_text(" ", strip=True) if link else cells[1])[:300] or row[:200],
                snippet=row[:2000],
                content_text=row,  # tender detail pages usually need a session/captcha; the row is the evidence
                published_at=parse_date(dates[0]) if dates else None,
                meta={"portal": source.url, "dates": dates[:3], "detail_link": href},
            )
        )
    return items


def _row_url(base: str, row: str) -> str:
    # A stable pseudo-URL per tender row (query param, since URL normalisation drops fragments).
    return f"{base}{'&' if '?' in base else '?'}lead_row={sha256(row)[:16]}"
