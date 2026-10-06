from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_user
from app.api.serializers import email_out, outreach_out
from app.db import get_db
from app.models import (
    PENDING_EMAIL_STATUSES,
    EmailMessage,
    EmailStatus,
    Outreach,
    OutreachStatus,
    Project,
    Suppression,
    log_activity,
    utcnow,
)
from app.services.suppression import is_suppressed, stop_outreach, suppress

router = APIRouter(tags=["emails"], dependencies=[Depends(require_user)])


@router.get("/emails")
def list_emails(
    db: Session = Depends(get_db),
    status: list[str] = Query(default=[]),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(EmailMessage)
    if status:
        stmt = stmt.where(EmailMessage.status.in_(status))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.options(
            selectinload(EmailMessage.outreach).selectinload(Outreach.project).selectinload(Project.company),
            selectinload(EmailMessage.outreach).selectinload(Outreach.contact),
        )
        .order_by(EmailMessage.created_at.desc()).limit(limit).offset(offset)
    ).all()
    items = []
    for m in rows:
        d = email_out(m)
        p = m.outreach.project
        d.update(project_id=p.id, project_title=p.title, grade=p.grade, score=p.score,
                 company_name=p.company.name if p.company else None,
                 contact_name=m.outreach.contact.name, contact_title=m.outreach.contact.title)
        items.append(d)
    return {"total": total, "items": items}


def _get(db: Session, email_id: int) -> EmailMessage:
    m = db.get(EmailMessage, email_id)
    if not m:
        raise HTTPException(404, "Email not found")
    return m


class EmailPatch(BaseModel):
    subject: str | None = None
    body_text: str | None = None


@router.patch("/emails/{email_id}")
def edit_email(email_id: int, body: EmailPatch, db: Session = Depends(get_db)):
    m = _get(db, email_id)
    if m.status not in PENDING_EMAIL_STATUSES:
        raise HTTPException(409, f"Cannot edit an email in status {m.status}")
    if body.subject is not None:
        m.subject = body.subject.strip()[:300]
    if body.body_text is not None:
        if "unsubscribe" not in body.body_text.lower():
            raise HTTPException(400, "The unsubscribe footer must be kept in the body")
        m.body_text = body.body_text
    m.generated_by = "edited"
    db.commit()
    return email_out(m)


@router.post("/emails/{email_id}/approve")
def approve(email_id: int, db: Session = Depends(get_db)):
    m = _get(db, email_id)
    if m.status != EmailStatus.DRAFT:
        raise HTTPException(409, f"Only drafts can be approved (status: {m.status})")
    if m.outreach.status != OutreachStatus.ACTIVE:
        raise HTTPException(409, f"Outreach is {m.outreach.status}")
    if is_suppressed(db, m.to_email):
        raise HTTPException(409, "Recipient is on the suppression list")
    m.status, m.approved_at = EmailStatus.APPROVED, utcnow()
    log_activity(db, "email", m.id, "approved")
    db.commit()
    return email_out(m)


@router.post("/emails/{email_id}/cancel")
def cancel(email_id: int, db: Session = Depends(get_db)):
    m = _get(db, email_id)
    if m.status not in PENDING_EMAIL_STATUSES:
        raise HTTPException(409, f"Cannot cancel an email in status {m.status}")
    m.status, m.error = EmailStatus.CANCELLED, "cancelled by user"
    if m.step == 0:
        stop_outreach(db, m.outreach, OutreachStatus.STOPPED_MANUAL, "initial email cancelled")
    db.commit()
    return email_out(m)


@router.post("/outreach/{outreach_id}/stop")
def stop(outreach_id: int, db: Session = Depends(get_db)):
    o = db.get(Outreach, outreach_id)
    if not o:
        raise HTTPException(404, "Outreach not found")
    stop_outreach(db, o, OutreachStatus.STOPPED_MANUAL, "stopped by user")
    db.commit()
    return outreach_out(o)


# ---------------------------------------------------------------- suppressions


@router.get("/suppressions")
def list_suppressions(db: Session = Depends(get_db), limit: int = Query(100, le=500), offset: int = 0):
    total = db.scalar(select(func.count(Suppression.id)))
    rows = db.scalars(select(Suppression).order_by(Suppression.created_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [
        {"id": s.id, "email": s.email, "domain": s.domain, "reason": s.reason, "note": s.note,
         "created_at": s.created_at} for s in rows
    ]}


class SuppressionIn(BaseModel):
    email: str | None = None
    domain: str | None = None
    note: str | None = None


@router.post("/suppressions")
def add_suppression(body: SuppressionIn, db: Session = Depends(get_db)):
    if not body.email and not body.domain:
        raise HTTPException(400, "email or domain required")
    s = suppress(db, email=body.email, domain=None if body.email else body.domain, reason="manual", note=body.note)
    db.commit()
    return {"id": s.id, "email": s.email, "domain": s.domain, "reason": s.reason}


@router.delete("/suppressions/{suppression_id}")
def delete_suppression(suppression_id: int, db: Session = Depends(get_db)):
    s = db.get(Suppression, suppression_id)
    if not s:
        raise HTTPException(404, "Not found")
    if s.reason == "unsubscribe":
        raise HTTPException(409, "Unsubscribes cannot be removed from the dashboard")
    db.delete(s)
    db.commit()
    return {"ok": True}
