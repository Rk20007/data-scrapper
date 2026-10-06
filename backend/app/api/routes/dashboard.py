from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_user
from app.api.serializers import lead_row, source_out
from app.db import get_db
from app.models import (
    ActivityLog,
    Company,
    Contact,
    EmailMessage,
    EmailStatus,
    Grade,
    InboundMessage,
    Outreach,
    Project,
    Source,
    utcnow,
)
from app.services.ai import get_ai
from app.services.runtime_settings import get_runtime

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_user)])


def _lead_query():
    return select(Project).options(
        selectinload(Project.company).selectinload(Company.contacts),
        selectinload(Project.evidence),
        selectinload(Project.outreaches).selectinload(Outreach.messages),
        selectinload(Project.outreaches).selectinload(Outreach.contact),
    )


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    since_day = utcnow() - timedelta(days=1)
    since_week = utcnow() - timedelta(days=7)
    by_grade = dict(
        db.execute(
            select(Project.grade, func.count()).where(Project.is_current.is_(True)).group_by(Project.grade)
        ).all()
    )
    by_status = dict(db.execute(select(Project.lead_status, func.count()).group_by(Project.lead_status)).all())
    email_counts = dict(db.execute(select(EmailMessage.status, func.count()).group_by(EmailMessage.status)).all())
    sent_today = db.scalar(select(func.count(EmailMessage.id)).where(
        EmailMessage.status == EmailStatus.SENT, EmailMessage.sent_at >= since_day)) or 0
    hot = db.scalars(
        _lead_query().where(Project.is_current.is_(True), Project.grade.in_([Grade.HOT, Grade.HIGH]))
        .order_by(Project.score.desc()).limit(10)
    ).all()
    replies = db.scalars(select(InboundMessage).order_by(InboundMessage.created_at.desc()).limit(8)).all()
    sources = db.scalars(select(Source).order_by(Source.last_status.desc().nullslast(), Source.name)).all()
    activity = db.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(15)).all()
    rt = get_runtime(db)
    return {
        "totals": {
            "companies": db.scalar(select(func.count(Company.id))) or 0,
            "quality_companies": db.scalar(select(func.count(Company.id)).where(Company.is_quality.is_(True))) or 0,
            "projects": db.scalar(select(func.count(Project.id))) or 0,
            "new_projects_7d": db.scalar(select(func.count(Project.id)).where(Project.created_at >= since_week)) or 0,
            "contacts_with_email": db.scalar(select(func.count(Contact.id)).where(Contact.email.is_not(None))) or 0,
            "emails_sent_today": sent_today,
            "drafts_pending": email_counts.get(EmailStatus.DRAFT, 0),
            "replies_7d": db.scalar(select(func.count(InboundMessage.id)).where(InboundMessage.created_at >= since_week)) or 0,
        },
        "by_grade": {g.value: by_grade.get(g.value, 0) for g in Grade},
        "by_status": by_status,
        "email_counts": email_counts,
        "hot_leads": [lead_row(p) for p in hot],
        "recent_replies": [
            {"id": r.id, "from_email": r.from_email, "subject": r.subject, "classification": r.classification,
             "summary": r.summary, "outreach_id": r.outreach_id, "received_at": r.received_at}
            for r in replies
        ],
        "sources": {
            "total": len(sources),
            "enabled": sum(1 for s in sources if s.enabled),
            "failing": [source_out(s) for s in sources if s.enabled and s.last_status == "error"][:10],
        },
        "activity": [
            {"id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id, "action": a.action,
             "detail": a.detail, "created_at": a.created_at}
            for a in activity
        ],
        "system": {"ai_enabled": get_ai().enabled, "send_mode": rt.email_send_mode,
                   "daily_send_limit": rt.daily_send_limit},
    }
