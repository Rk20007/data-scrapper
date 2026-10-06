import logging
from datetime import timedelta

from sqlalchemy import func, or_, select

from app.config import settings
from app.db import session_scope
from app.models import (
    Company,
    DocStatus,
    Document,
    EmailMessage,
    EmailStatus,
    Grade,
    InboundMessage,
    Project,
    Source,
    utcnow,
)
from app.services import inbox, outreach, pipeline
from app.services.contacts import enrich_company_contacts
from app.services.entities import rescore_all, rescore_project
from app.services.http import get_fetcher
from app.services.notifications import notify
from app.services.redis_client import single_flight
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- sources & documents


@celery_app.task
def dispatch_due_sources() -> int:
    with session_scope() as db:
        ids = [s.id for s in pipeline.due_sources(db)]
    for sid in ids:
        run_source.delay(sid)
    return len(ids)


@celery_app.task
def run_source(source_id: int) -> int:
    with single_flight(f"source:{source_id}", timeout=1800) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            source = db.get(Source, source_id)
            if not source:
                return 0
            ids = pipeline.run_source(db, source, get_fetcher())
    for doc_id in ids:
        process_document.delay(doc_id)
    return len(ids)


@celery_app.task(rate_limit="30/m")
def process_document(doc_id: int) -> int | None:
    with session_scope() as db:
        doc = db.get(Document, doc_id)
        if not doc:
            return None
        project = pipeline.process_document(db, doc, get_fetcher())
        return project.id if project else None


@celery_app.task
def process_pending_documents(limit: int = 100) -> int:
    """Safety net: retry docs left NEW (lost tasks) or PENDING_AI (AI was down / not configured)."""
    with session_scope() as db:
        ids = db.scalars(
            select(Document.id)
            .where(
                Document.status.in_([DocStatus.NEW, DocStatus.PENDING_AI]),
                Document.created_at < utcnow() - timedelta(minutes=5),
            )
            .order_by(Document.id)
            .limit(limit)
        ).all()
    for i in ids:
        process_document.delay(i)
    return len(ids)


# ---------------------------------------------------------------- companies


@celery_app.task
def dispatch_company_monitoring() -> int:
    with session_scope() as db:
        ids = db.scalars(
            select(Company.id).where(
                Company.monitor_website.is_(True),
                or_(Company.is_quality.is_(True), Company.is_quality.is_(None), Company.grade != Grade.LOW),
            )
        ).all()
    for cid in ids:
        monitor_company.delay(cid)
    return len(ids)


@celery_app.task
def monitor_company(company_id: int) -> int:
    with single_flight(f"company:{company_id}", timeout=1800) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            company = db.get(Company, company_id)
            if not company:
                return 0
            ids = pipeline.monitor_company_website(db, company, get_fetcher())
    for doc_id in ids:
        process_document.delay(doc_id)
    return len(ids)


@celery_app.task
def discover() -> int:
    with single_flight("discover", timeout=3600) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            return pipeline.discover_companies(db, get_fetcher())


@celery_app.task
def assess_pending_companies(limit: int = 20) -> int:
    with session_scope() as db:
        ids = db.scalars(
            select(Company.id).where(Company.last_assessed_at.is_(None)).order_by(Company.id).limit(limit)
        ).all()
    for cid in ids:
        assess_company.delay(cid)
    return len(ids)


@celery_app.task
def assess_company(company_id: int) -> None:
    with session_scope() as db:
        company = db.get(Company, company_id)
        if company:
            pipeline.assess_company(db, company, get_fetcher())
            company.last_assessed_at = company.last_assessed_at or utcnow()  # avoid re-queuing on failure


@celery_app.task
def dispatch_contact_enrichment(limit: int = 15) -> int:
    """Enrich companies that have a promising project but no reachable contact (stale after 30 days)."""
    with session_scope() as db:
        stale = utcnow() - timedelta(days=30)
        ids = db.scalars(
            select(Company.id)
            .join(Project, Project.company_id == Company.id)
            .where(
                Project.is_current.is_(True),
                Project.grade.in_([Grade.HOT, Grade.HIGH, Grade.WARM]),
                or_(Company.last_enriched_at.is_(None), Company.last_enriched_at < stale),
            )
            .group_by(Company.id)
            .order_by(func.max(Project.score).desc())
            .limit(limit)
        ).all()
    for cid in ids:
        enrich_company.delay(cid)
    return len(ids)


@celery_app.task
def enrich_company(company_id: int) -> int:
    with single_flight(f"company:{company_id}", timeout=1800) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            company = db.get(Company, company_id)
            if not company:
                return 0
            n = enrich_company_contacts(db, get_fetcher(), company)
            for p in company.projects:
                rescore_project(db, p)
            return n


# ---------------------------------------------------------------- email


@celery_app.task
def plan_outreach() -> int:
    with single_flight("plan_outreach", timeout=900) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            return outreach.plan_outreach_batch(db)


@celery_app.task
def schedule_followups() -> int:
    with single_flight("followups", timeout=900) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            return outreach.schedule_followups(db)


@celery_app.task
def send_queue_tick() -> dict:
    with single_flight("send_queue", timeout=300) as ok:
        if not ok:
            return {"sent": 0, "reason": "locked"}
        with session_scope() as db:
            return outreach.process_send_queue(db)


@celery_app.task
def poll_inbox() -> int:
    with single_flight("inbox", timeout=600) as ok:
        if not ok:
            return 0
        with session_scope() as db:
            return inbox.poll_inbox(db)


@celery_app.task
def reap_stuck() -> int:
    with session_scope() as db:
        return outreach.reap_stuck_sending(db)


@celery_app.task
def rescore() -> int:
    with session_scope() as db:
        return rescore_all(db)


@celery_app.task
def daily_digest() -> None:
    since = utcnow() - timedelta(days=1)
    with session_scope() as db:
        new_hot = db.scalars(
            select(Project).where(Project.created_at >= since, Project.grade.in_([Grade.HOT, Grade.HIGH]))
            .order_by(Project.score.desc()).limit(10)
        ).all()
        sent = db.scalar(select(func.count(EmailMessage.id)).where(
            EmailMessage.status == EmailStatus.SENT, EmailMessage.sent_at >= since)) or 0
        replies = db.scalar(select(func.count(InboundMessage.id)).where(InboundMessage.created_at >= since)) or 0
        pending = db.scalar(select(func.count(EmailMessage.id)).where(EmailMessage.status == EmailStatus.DRAFT)) or 0
        failing = db.scalars(select(Source.name).where(Source.enabled.is_(True), Source.last_status == "error")).all()
        lines = [f"Emails sent: {sent} · Replies: {replies} · Drafts awaiting approval: {pending}"]
        lines += [f"• [{p.grade}] {p.company.name if p.company else p.tender_authority or 'Tender'} — {p.title}" for p in new_hot]
        if failing:
            lines.append(f"Sources failing: {', '.join(failing[:8])}")
    notify(f"Daily digest — {len(new_hot)} new HOT/HIGH leads", lines, settings.dashboard_url)
