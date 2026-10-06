"""Suppression list + signed unsubscribe tokens."""

import base64
import hashlib
import hmac

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Contact,
    EmailStatus,
    LeadStatus,
    Outreach,
    OutreachStatus,
    PENDING_EMAIL_STATUSES,
    Suppression,
    log_activity,
)
from app.services.extraction import registered_domain


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_unsubscribe_token(email: str) -> str:
    email = email.lower().strip()
    sig = hmac.new(settings.secret_key.encode(), f"unsub:{email}".encode(), hashlib.sha256).digest()[:16]
    return f"{_b64(email.encode())}.{_b64(sig)}"


def verify_unsubscribe_token(token: str) -> str | None:
    try:
        e64, s64 = token.split(".", 1)
        email = _unb64(e64).decode()
        expected = make_unsubscribe_token(email).split(".", 1)[1]
        return email if hmac.compare_digest(expected, s64) else None
    except (ValueError, UnicodeDecodeError):
        return None


def unsubscribe_url(email: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/u/{make_unsubscribe_token(email)}"


def is_suppressed(db: Session, email: str) -> bool:
    email = email.lower().strip()
    domain = registered_domain(email)
    q = select(Suppression.id).where(
        or_(Suppression.email == email, (Suppression.email.is_(None)) & (Suppression.domain == domain))
    )
    return db.scalar(q.limit(1)) is not None


def suppress(db: Session, *, email: str | None = None, domain: str | None = None, reason: str, note: str | None = None) -> Suppression:
    if not email and not domain:
        raise ValueError("email or domain required")
    email = email.lower().strip() if email else None
    domain = domain or (registered_domain(email) if email else None)
    domain = domain.lower() if domain else None
    if email:
        existing = db.scalar(select(Suppression).where(Suppression.email == email))
    else:
        existing = db.scalar(select(Suppression).where(Suppression.email.is_(None), Suppression.domain == domain))
    if existing:
        return existing
    row = Suppression(email=email, domain=domain, reason=reason, note=note)
    db.add(row)
    db.flush()
    log_activity(db, "suppression", row.id, "added", email=email, domain=domain, reason=reason)

    # Stop everything in flight to the suppressed address(es).
    contacts_q = select(Contact)
    contacts_q = contacts_q.where(Contact.email == email) if email else contacts_q.where(Contact.email.like(f"%@{domain}"))
    status_for = {
        "unsubscribe": OutreachStatus.STOPPED_UNSUBSCRIBED,
        "declined": OutreachStatus.STOPPED_DECLINED,
        "bounce": OutreachStatus.STOPPED_BOUNCED,
    }.get(reason, OutreachStatus.STOPPED_MANUAL)
    for contact in db.scalars(contacts_q):
        contact.do_not_contact = True
        if reason == "bounce":
            contact.email_status = "bounced"
        for o in db.scalars(select(Outreach).where(Outreach.contact_id == contact.id)):
            stop_outreach(db, o, status_for, f"suppressed: {reason}")
            if reason == "unsubscribe":
                o.project.lead_status = LeadStatus.UNSUBSCRIBED
    return row


def stop_outreach(db: Session, outreach: Outreach, status: str, reason: str) -> None:
    if outreach.status in (OutreachStatus.ACTIVE, OutreachStatus.PAUSED, OutreachStatus.COMPLETED):
        outreach.status = status
        outreach.stopped_reason = reason
    outreach.next_action_at = None
    for m in outreach.messages:
        if m.status in PENDING_EMAIL_STATUSES:
            m.status = EmailStatus.CANCELLED
            m.error = reason
    log_activity(db, "outreach", outreach.id, "stopped", status=status, reason=reason)
