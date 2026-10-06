"""Sources, runtime settings and manual job triggers."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.serializers import source_out
from app.config import settings
from app.db import get_db
from app.models import Source, SourceKind
from app.services.ai import get_ai
from app.services.runtime_settings import get_runtime, update_runtime

router = APIRouter(tags=["admin"], dependencies=[Depends(require_user)])

COLLECTABLE_KINDS = {SourceKind.NEWS_RSS, SourceKind.SEARCH, SourceKind.LISTING, SourceKind.TENDER_TABLE}


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return {"items": [source_out(s) for s in db.scalars(select(Source).order_by(Source.kind, Source.name))]}


class SourceIn(BaseModel):
    name: str
    kind: SourceKind
    url: str | None = None
    config: dict = {}
    enabled: bool = True
    interval_minutes: int = 360


def _validate_source(kind: str, url: str | None, config: dict) -> None:
    if kind not in COLLECTABLE_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(COLLECTABLE_KINDS)}")
    if kind in (SourceKind.LISTING, SourceKind.TENDER_TABLE) and not url:
        raise HTTPException(400, "url is required for this kind")
    if kind == SourceKind.SEARCH and not config.get("query"):
        raise HTTPException(400, "config.query is required for search sources")
    if kind == SourceKind.NEWS_RSS and not (url or config.get("query")):
        raise HTTPException(400, "news_rss needs a feed url or config.query")


@router.post("/sources")
def create_source(body: SourceIn, db: Session = Depends(get_db)):
    _validate_source(body.kind, body.url, body.config)
    if db.scalar(select(Source.id).where(Source.name == body.name)):
        raise HTTPException(409, "A source with this name exists")
    s = Source(**body.model_dump())
    s.interval_minutes = max(30, s.interval_minutes)
    db.add(s)
    db.commit()
    return source_out(s)


class SourcePatch(BaseModel):
    name: str | None = None
    url: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    interval_minutes: int | None = None


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourcePatch, db: Session = Depends(get_db)):
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    _validate_source(s.kind, s.url, s.config or {})
    s.interval_minutes = max(30, s.interval_minutes)
    db.commit()
    return source_out(s)


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/sources/{source_id}/run")
def run_source_now(source_id: int):
    from app.workers.tasks import run_source

    return {"task_id": run_source.delay(source_id).id}


@router.post("/sources/seed")
def seed(db: Session = Depends(get_db)):
    from app.seed import seed_sources

    n = seed_sources(db)
    db.commit()
    return {"added": n}


# ---------------------------------------------------------------- settings


@router.get("/settings")
def get_settings_view(db: Session = Depends(get_db)):
    return {
        "runtime": asdict(get_runtime(db)),
        "system": {
            "ai_enabled": get_ai().enabled,
            "openai_model": settings.openai_model,
            "search_provider": settings.search_provider,
            "smtp_configured": bool(settings.smtp_host),
            "imap_configured": bool(settings.imap_host),
            "sender": f"{settings.sender_name} <{settings.sender_email}>" if settings.sender_email else None,
            "sender_address_set": bool(settings.sender_address),
            "notifications": [n for n, ok in (("slack", settings.slack_webhook_url),
                                              ("telegram", settings.telegram_bot_token),
                                              ("email", settings.notify_email)) if ok],
            "target_clusters": settings.target_clusters,
            "timezone": settings.timezone,
        },
    }


@router.put("/settings")
def put_settings(body: dict, db: Session = Depends(get_db)):
    if body.get("email_send_mode") == "auto":
        missing = [k for k in ("smtp_host", "sender_email", "sender_address") if not getattr(settings, k)]
        if missing:
            raise HTTPException(400, f"Cannot enable auto-send; configure: {', '.join(missing)}")
    try:
        rt = update_runtime(db, body)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return {"runtime": asdict(rt)}


@router.get("/ai-usage")
def ai_usage(days: int = 30):
    from app.services.ai import usage_summary

    return usage_summary(min(max(days, 1), 120))


# ---------------------------------------------------------------- jobs

JOBS = {
    "dispatch_sources": "dispatch_due_sources",
    "process_documents": "process_pending_documents",
    "monitor_websites": "dispatch_company_monitoring",
    "discover_companies": "discover",
    "assess_companies": "assess_pending_companies",
    "enrich_contacts": "dispatch_contact_enrichment",
    "plan_outreach": "plan_outreach",
    "schedule_followups": "schedule_followups",
    "send_queue": "send_queue_tick",
    "poll_inbox": "poll_inbox",
    "rescore": "rescore",
    "daily_digest": "daily_digest",
}


@router.post("/jobs/{name}")
def run_job(name: str):
    from app.workers import tasks

    if name not in JOBS:
        raise HTTPException(404, f"Unknown job. Available: {sorted(JOBS)}")
    return {"task_id": getattr(tasks, JOBS[name]).delay().id}
