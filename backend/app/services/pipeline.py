"""Ingestion → pre-filter → AI verification → project upsert → scoring → notification."""

import logging
from datetime import timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    GRADE_RANK,
    Company,
    DocStatus,
    Document,
    Grade,
    Project,
    Source,
    SourceKind,
    log_activity,
    utcnow,
)
from app.services.ai import AIError, get_ai
from app.services.collectors import RawItem
from app.services.collectors.sources import collect
from app.services.entities import is_company_domain, rescore_company, upsert_company, upsert_project_from_classification
from app.services.extraction import (
    clean_text,
    detect_cluster,
    extract_page,
    new_lines,
    normalize_url,
    prefilter,
    registered_domain,
    sha256,
    url_hash,
)
from app.services.http import Fetcher, FetchError
from app.services.notifications import notify
from app.services.runtime_settings import get_runtime
from app.services.search import get_search_provider

log = logging.getLogger(__name__)

MAX_ITEM_AGE_DAYS = 540
NEWS_HINTS = ("news", "press", "media", "blog", "investor", "announcement", "update", "release", "expansion",
              "project", "sustainab", "career")


# ---------------------------------------------------------------- ingestion


def ingest_items(db: Session, items: list[RawItem], *, source: Source | None, source_kind: str,
                 company_id: int | None = None) -> list[int]:
    new_ids: list[int] = []
    cutoff = utcnow() - timedelta(days=MAX_ITEM_AGE_DAYS)
    for item in items:
        if not item.url.startswith(("http://", "https://")):
            continue
        if item.published_at and item.published_at < cutoff:
            continue
        h = url_hash(item.url)
        if db.scalar(select(Document.id).where(Document.url_hash == h)):
            continue
        doc = Document(
            source_id=source.id if source else None,
            source_kind=source_kind,
            company_id=company_id,
            url=normalize_url(item.url),
            url_hash=h,
            title=item.title,
            snippet=item.snippet,
            content_text=item.content_text,
            analysis_text=item.content_text,
            content_hash=sha256(item.content_text) if item.content_text else None,
            published_at=item.published_at,
            meta=item.meta or None,
            status=DocStatus.NEW,
        )
        db.add(doc)
        db.flush()
        new_ids.append(doc.id)
    return new_ids


def run_source(db: Session, source: Source, fetcher: Fetcher) -> list[int]:
    source.last_run_at = utcnow()
    try:
        items = collect(source, fetcher)
        ids = ingest_items(db, items, source=source, source_kind=source.kind)
        source.last_status, source.last_error = "ok", None
        source.last_success_at = utcnow()
        source.items_last_run = len(ids)
        return ids
    except Exception as exc:  # noqa: BLE001 — surface any collector failure on the dashboard
        log.warning("Source %s failed: %s", source.name, exc)
        source.last_status, source.last_error = "error", str(exc)[:2000]
        source.items_last_run = 0
        return []


def due_sources(db: Session) -> list[Source]:
    now = utcnow()
    out = []
    for s in db.scalars(select(Source).where(Source.enabled.is_(True))):
        last = s.last_run_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if not last or now - last >= timedelta(minutes=s.interval_minutes):
            out.append(s)
    return out


# ---------------------------------------------------------------- processing


def _pdf_text(data: bytes, max_pages: int = 15) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


def _maybe_fetch_full_text(doc: Document, fetcher: Fetcher) -> None:
    if doc.content_text and not (doc.meta or {}).get("is_document"):
        return
    host = urlsplit(doc.url).netloc
    if host.endswith("news.google.com"):
        return  # Google News article links are JS redirects; keep title + snippet
    try:
        resp = fetcher.get(doc.url, retries=1)
    except FetchError as exc:
        doc.error = str(exc)[:500]
        return
    ctype = resp.headers.get("content-type", "text/html")
    if "pdf" in ctype or doc.url.lower().endswith(".pdf"):
        if len(resp.content) > 15_000_000:
            return
        try:
            text = clean_text(_pdf_text(resp.content))
        except Exception as exc:  # noqa: BLE001 — malformed/scanned PDFs
            doc.error = f"pdf: {exc}"[:500]
            return
        if text.strip():
            snippet = doc.content_text or ""
            doc.content_text = f"{snippet}\n{text}"[:60000]
            doc.analysis_text = doc.content_text
            doc.content_hash = sha256(doc.content_text)
        return
    if "html" not in ctype:
        return
    ex = extract_page(resp.text, str(resp.url))
    doc.content_text = ex.text[:60000]
    doc.analysis_text = doc.content_text
    doc.content_hash = sha256(doc.content_text)
    doc.published_at = doc.published_at or ex.published_at
    doc.title = doc.title or ex.title


def process_document(db: Session, doc: Document, fetcher: Fetcher) -> Project | None:
    if doc.status not in (DocStatus.NEW, DocStatus.PENDING_AI):
        return None
    company = db.get(Company, doc.company_id) if doc.company_id else None

    # Cheap filter on the snippet first, then fetch the full article only when promising.
    snippet_text = f"{doc.title or ''}\n{doc.snippet or ''}\n{doc.content_text or ''}"
    location_known = doc.source_kind == SourceKind.COMPANY_WEBSITE and bool(company and company.cluster)
    if doc.source_kind in (SourceKind.NEWS_RSS, SourceKind.SEARCH):
        pf_snip = prefilter(snippet_text, location_known=True)
        if not pf_snip.project_hits:
            doc.status, doc.prefilter_hits = DocStatus.FILTERED_OUT, pf_snip.as_dict()
            return None
    _maybe_fetch_full_text(doc, fetcher)

    body = doc.analysis_text or doc.content_text or ""
    full = f"{doc.title or ''}\n{doc.snippet or ''}\n{body}"
    pf = prefilter(full, location_known=location_known)
    doc.prefilter_hits = pf.as_dict()
    if not pf.passed:
        doc.status = DocStatus.FILTERED_OUT
        return None

    ai = get_ai()
    if not ai.enabled:
        doc.status = DocStatus.PENDING_AI
        return None
    try:
        result = ai.classify_document(
            title=doc.title or "",
            url=doc.url,
            text=full,
            published_at=doc.published_at.date().isoformat() if doc.published_at else None,
            source_kind=doc.source_kind,
            company_hint=f"{company.name} ({company.cluster or 'cluster unknown'})" if company else None,
        )
    except AIError as exc:
        doc.status, doc.error = DocStatus.PENDING_AI, str(exc)[:1000]
        return None

    doc.ai_result = result.model_dump()
    if not result.cluster:
        result.cluster = detect_cluster(result.location_text) if result.is_relevant else None
    if not result.is_relevant or result.opportunity_kind == "none":
        doc.status = DocStatus.IRRELEVANT
        return None

    doc.status = DocStatus.CLASSIFIED
    project, created = upsert_project_from_classification(db, doc, result)
    maybe_notify_project(db, project, created)
    return project


def maybe_notify_project(db: Session, project: Project, created: bool) -> None:
    rt = get_runtime(db)
    if GRADE_RANK[Grade(project.grade)] < GRADE_RANK[Grade(rt.notify_min_grade)] or not project.is_current:
        return
    if project.notified_grade and GRADE_RANK[Grade(project.notified_grade)] >= GRADE_RANK[Grade(project.grade)]:
        return  # already notified at this grade or higher
    project.notified_grade = project.grade
    company = project.company.name if project.company else (project.tender_authority or "Tender")
    ev = project.evidence[0] if project.evidence else None
    notify(
        f"{project.grade} lead: {company} — {project.title}"[:200],
        [
            f"Type: {project.project_type} · Stage: {project.stage} · Cluster: {project.cluster or '-'}",
            f"Score: {project.score}" + (f" · ₹{project.investment_inr_crore:g} Cr" if project.investment_inr_crore else ""),
            *(f"• {f}" for f in (project.key_facts or [])[:3]),
            f"Source: {ev.url}" if ev else "",
        ],
        f"{settings.dashboard_url}/leads/{project.id}",
    )
    log_activity(db, "project", project.id, "notified", grade=project.grade, new=created)


# ---------------------------------------------------------------- company websites


def find_company_website(db: Session, company: Company, fetcher: Fetcher) -> None:
    if company.website:
        return
    provider = get_search_provider(fetcher)
    if provider.name == "none":
        return
    try:
        results = provider.search(f'"{company.name}" official website', num=5)
    except FetchError:
        return
    for r in results:
        domain = registered_domain(r.url)
        if is_company_domain(domain) and not db.scalar(select(Company.id).where(Company.domain == domain)):
            first = company.normalized_name.split()[0] if company.normalized_name else ""
            if first and first[:4] in domain:
                parts = urlsplit(r.url)
                company.website, company.domain = f"{parts.scheme}://{parts.netloc}", domain
                return


def monitor_company_website(db: Session, company: Company, fetcher: Fetcher) -> list[int]:
    """Re-crawl a company's homepage + news/press pages; only *changed* text is sent to AI."""
    find_company_website(db, company, fetcher)
    company.last_monitored_at = utcnow()
    if not company.website:
        return []
    try:
        home = fetcher.get(company.website)
    except FetchError as exc:
        log.info("Monitor fetch failed for %s: %s", company.website, exc)
        return []
    ex = extract_page(home.text, str(home.url))
    host = urlsplit(str(home.url)).netloc
    pages = {str(home.url): ex}
    for href, text in ex.links:
        if len(pages) >= settings.crawler_max_pages_per_site:
            break
        if urlsplit(href).netloc != host or href in pages or href.lower().endswith((".pdf", ".jpg", ".png", ".zip")):
            continue
        if any(h in f"{href} {text}".lower() for h in NEWS_HINTS):
            try:
                resp = fetcher.get(href, retries=0)
                if "html" in resp.headers.get("content-type", "text/html"):
                    pages[href] = extract_page(resp.text, str(resp.url))
            except FetchError:
                continue

    changed: list[int] = []
    for url, page in pages.items():
        h = url_hash(url)
        text_hash = sha256(page.text)
        doc = db.scalar(select(Document).where(Document.url_hash == h))
        if doc and doc.content_hash == text_hash:
            continue
        delta = new_lines(doc.content_text if doc else None, page.text)
        if doc:
            if not delta.strip():
                doc.content_hash, doc.content_text = text_hash, page.text
                continue
            doc.content_text, doc.analysis_text, doc.content_hash = page.text, delta, text_hash
            doc.status, doc.fetched_at, doc.title = DocStatus.NEW, utcnow(), page.title
            doc.published_at = page.published_at or utcnow()
        else:
            doc = Document(
                source_kind=SourceKind.COMPANY_WEBSITE, company_id=company.id, url=normalize_url(url), url_hash=h,
                title=page.title, content_text=page.text, analysis_text=page.text, content_hash=text_hash,
                published_at=page.published_at, status=DocStatus.NEW,
            )
            db.add(doc)
        db.flush()
        changed.append(doc.id)
    return changed


# ---------------------------------------------------------------- discovery


DISCOVERY_QUERIES = [
    "{c} industrial area manufacturing plant company",
    "{c} RIICO new factory",
    "{c} Rajasthan warehouse logistics park",
    "{c} plant expansion investment crore",
]


def discover_companies(db: Session, fetcher: Fetcher) -> int:
    ai = get_ai()
    provider = get_search_provider(fetcher)
    if not ai.enabled or provider.name == "none":
        return 0
    count_before = db.scalar(select(func.count(Company.id))) or 0
    for cluster in settings.target_clusters:
        for template in DISCOVERY_QUERIES:
            try:
                results = provider.search(template.format(c=cluster), num=10, recency_days=365)
            except FetchError as exc:
                log.warning("Discovery search failed: %s", exc)
                continue
            if not results:
                continue
            text = "\n\n".join(f"{r.title}\n{r.snippet}\nURL: {r.url}" for r in results)
            try:
                found = ai.discover_companies(text)
            except AIError as exc:
                log.warning("Discovery extraction failed: %s", exc)
                continue
            for fc in found:
                upsert_company(db, fc.name, website=fc.website, cluster=fc.cluster or cluster,
                               industry=fc.industry, source="discovery")
    db.flush()
    return (db.scalar(select(func.count(Company.id))) or 0) - count_before


def assess_company(db: Session, company: Company, fetcher: Fetcher) -> None:
    """Estimate size/quality from the company's homepage plus public search snippets."""
    ai = get_ai()
    if not ai.enabled:
        return
    chunks = []
    if company.website:
        try:
            resp = fetcher.get(company.website, retries=0)
            chunks.append(extract_page(resp.text, str(resp.url)).text[:5000])
        except FetchError:
            pass
    provider = get_search_provider(fetcher)
    if provider.name != "none":
        try:
            for r in provider.search(f'"{company.name}" employees turnover plant', num=6):
                chunks.append(f"{r.title}: {r.snippet}")
        except FetchError:
            pass
    if not chunks:
        return
    try:
        a = ai.assess_company(company.name, "\n".join(chunks))
    except AIError as exc:
        log.warning("Assessment failed for %s: %s", company.name, exc)
        return
    company.size_tier, company.employee_estimate = a.size_tier, a.employee_estimate
    company.is_quality, company.quality_reason = a.is_quality, a.reason
    company.industry = company.industry or a.industry
    company.last_assessed_at = utcnow()
    rescore_company(db, company)
