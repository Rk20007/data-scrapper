"""HTML → text, link/email extraction, keyword pre-filter and normalisation helpers."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import tldextract
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from app.config import settings

_tld = tldextract.TLDExtract(suffix_list_urls=())  # offline: use bundled public-suffix snapshot

PROJECT_TERMS = [
    "new factory", "new plant", "new unit", "manufacturing facility", "manufacturing plant", "production facility",
    "greenfield", "brownfield", "expansion", "expand", "capacity addition", "capacity expansion", "capex",
    "warehouse", "warehousing", "logistics park", "industrial park", "fulfilment centre", "fulfillment center",
    "peb", "pre-engineered", "pre engineered", "industrial shed", "factory shed", "factory building",
    "civil work", "civil works", "construction", "epc", "turnkey", "boundary wall", "foundation stone",
    "bhoomi pujan", "bhumi pujan", "groundbreaking", "ground-breaking", "land allotment", "allotted land",
    "acquired land", "plot allotment", "mou", "investment", "invest", "commissioning", "set up", "setting up",
    "to build", "building", "infrastructure", "road work", "drainage", "sewerage", "tender", "nit",
    # Hindi: construction, factory, warehouse, expansion, allotment, tender, investment, plot, building
    "निर्माण", "फैक्ट्री", "कारखाना", "वेयरहाउस", "गोदाम", "विस्तार", "आवंटन", "निविदा", "निवेश", "भूखण्ड", "भवन",
]

LOCATION_TERMS = [
    "bhiwadi", "khushkhera", "khuskhera", "khushkheda", "tapukara", "tapukda", "neemrana", "nimrana",
    "chopanki", "pathredi", "kahrani", "ghiloth", "sotanala", "shahjahanpur", "keshwana", "majrakath",
    "tijara", "khairthal", "behror", "kotputli", "alwar",
    # Devanagari spellings used in RIICO / state notices
    "भिवाड़ी", "भिवाडी", "खुशखेड़ा", "खुशखेडा", "टपूकड़ा", "टपूकडा", "नीमराना", "घीलोठ", "चौपानकी", "तिजारा", "अलवर",
]

CLUSTER_ALIASES = {
    "Bhiwadi": ["bhiwadi", "chopanki", "kahrani", "pathredi", "sare khurd", "भिवाड़ी", "भिवाडी", "चौपानकी"],
    "Khushkhera": ["khushkhera", "khuskhera", "khushkheda", "karoli", "खुशखेड़ा", "खुशखेडा"],
    "Tapukara": ["tapukara", "tapukda", "टपूकड़ा", "टपूकडा"],
    "Neemrana": ["neemrana", "nimrana", "ghiloth", "majrakath", "shahjahanpur", "keshwana", "sotanala", "नीमराना", "घीलोठ"],
}

_COMPANY_SUFFIXES = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|corp|corporation|company|co|plc|india|gmbh|ag)\b\.?", re.I
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BAD_EMAIL_TLDS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ref"}


@dataclass
class PageExtract:
    title: str
    text: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)
    emails: set[str] = field(default_factory=set)
    published_at: datetime | None = None


def extract_page(html: str, base_url: str) -> PageExtract:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:500]

    published = None
    for attrs in (
        {"property": "article:published_time"},
        {"name": "pubdate"},
        {"name": "publish-date"},
        {"itemprop": "datePublished"},
        {"name": "date"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            published = parse_date(tag["content"])
            if published:
                break
    if not published:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            published = parse_date(t["datetime"])

    links: list[tuple[str, str]] = []
    emails: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(addr):
                emails.add(addr.lower())
            continue
        if href.startswith(("javascript:", "#", "tel:")):
            continue
        links.append((urljoin(base_url, href), a.get_text(" ", strip=True)[:200]))

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "footer", "header"]):
        # keep footer text for contact pages: emails/addresses usually live there
        if tag.name == "footer":
            continue
        tag.decompose()
    text = clean_text(soup.get_text("\n", strip=True))
    emails |= find_emails(text)
    return PageExtract(title=title, text=text, links=links, emails=emails, published_at=published)


def clean_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    out, prev = [], None
    for ln in lines:
        if ln and ln != prev:
            out.append(ln)
        prev = ln
    return "\n".join(out)


def find_emails(text: str) -> set[str]:
    deobf = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text, flags=re.I)
    deobf = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", deobf, flags=re.I)
    found = set()
    for m in EMAIL_RE.findall(deobf):
        e = m.strip(".").lower()
        if not e.endswith(_BAD_EMAIL_TLDS) and "example." not in e:
            found.add(e)
    return found


def new_lines(old: str | None, new: str) -> str:
    """Lines present in `new` but not in `old` — used to analyse only changed website content."""
    if not old:
        return new
    seen = set(old.splitlines())
    return "\n".join(ln for ln in new.splitlines() if ln not in seen)


@dataclass
class PrefilterResult:
    project_hits: list[str]
    location_hits: list[str]
    passed: bool

    def as_dict(self) -> dict:
        return {"project_hits": self.project_hits, "location_hits": self.location_hits, "passed": self.passed}


def _hits(terms: list[str], text: str) -> list[str]:
    return [t for t in terms if re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", text)]


def prefilter(text: str, *, location_known: bool = False) -> PrefilterResult:
    low = text.lower()
    p = _hits(PROJECT_TERMS, low)
    loc = _hits(LOCATION_TERMS, low)
    return PrefilterResult(p, loc, bool(p) and (bool(loc) or location_known))


def detect_cluster(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    for cluster, aliases in CLUSTER_ALIASES.items():
        if cluster in settings.target_clusters and any(a in low for a in aliases):
            return cluster
    return None


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def url_hash(url: str) -> str:
    return sha256(normalize_url(url))


def registered_domain(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    if "@" in url_or_host:
        url_or_host = url_or_host.split("@", 1)[1]
    ext = _tld(url_or_host)
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


def normalize_company_name(name: str) -> str:
    n = name.lower().replace("&", " and ")
    n = re.sub(r"[^\w\s]", " ", n)
    n = _COMPANY_SUFFIXES.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = dateparser.parse(str(value), dayfirst=True, fuzzy=True)
        except (ValueError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"
