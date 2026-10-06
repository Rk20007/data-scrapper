"""IMAP polling: match replies to outreach, classify them, and stop sequences."""

import email
import hashlib
import imaplib
import logging
import re
from email.message import Message
from email.policy import default as default_policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Company,
    Contact,
    EmailMessage,
    InboundMessage,
    LeadStatus,
    Outreach,
    OutreachStatus,
    ReplyClass,
    log_activity,
    utcnow,
)
from app.services.ai import AIError, get_ai
from app.services.extraction import EMAIL_RE, registered_domain
from app.services.notifications import notify
from app.services.suppression import stop_outreach, suppress

log = logging.getLogger(__name__)

_UNSUB_RE = re.compile(r"\b(unsubscribe|remove me|stop (emailing|sending)|do not (email|contact)|opt.?out)\b", re.I)
_DECLINE_RE = re.compile(
    r"\b(not interested|no requirement|no such requirement|already (have|finali[sz]ed)|not required|"
    r"no need|we are not looking|please don'?t)\b", re.I)
_OOO_RE = re.compile(r"\b(out of (the )?office|on leave|away from (the )?office|auto.?reply|automatic reply)\b", re.I)
_QUOTE_SPLIT = re.compile(r"^(On .+wrote:|-----Original Message-----|From: .+)$", re.M)


def _text_body(msg: Message) -> str:
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        from bs4 import BeautifulSoup

        content = BeautifulSoup(content, "lxml").get_text("\n")
    return content


def strip_quoted(body: str) -> str:
    body = _QUOTE_SPLIT.split(body)[0]
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith(">")).strip()


def is_bounce(msg: Message, from_addr: str) -> bool:
    local = from_addr.split("@")[0].lower()
    return (
        local in ("mailer-daemon", "postmaster")
        or msg.get_content_type() == "multipart/report"
        or "delivery status notification" in (msg.get("Subject") or "").lower()
        or "undeliver" in (msg.get("Subject") or "").lower()
    )


def bounced_recipients(msg: Message, raw_text: str) -> set[str]:
    found = set()
    for m in re.finditer(r"(?:Final|Original)-Recipient:\s*rfc822;\s*(\S+)", raw_text, re.I):
        found.add(m.group(1).strip("<>").lower())
    if not found:
        for m in re.finditer(r"^To:\s*(.+)$", raw_text, re.M | re.I):
            for _, addr in getaddresses([m.group(1)]):
                if EMAIL_RE.fullmatch(addr or ""):
                    found.add(addr.lower())
    return found


def heuristic_classify(subject: str, body: str) -> str:
    text = f"{subject}\n{body}"
    if _UNSUB_RE.search(text):
        return ReplyClass.UNSUBSCRIBE
    if _OOO_RE.search(text):
        return ReplyClass.OUT_OF_OFFICE
    if _DECLINE_RE.search(text):
        return ReplyClass.NOT_INTERESTED
    return ReplyClass.OTHER


def classify(subject: str, body: str) -> tuple[str, str | None]:
    heuristic = heuristic_classify(subject, body)
    if heuristic == ReplyClass.UNSUBSCRIBE:
        return heuristic, None  # never let a model overrule an explicit opt-out
    ai = get_ai()
    if ai.enabled:
        try:
            r = ai.classify_reply(subject, body)
            return r.classification, r.summary
        except AIError as exc:
            log.warning("Reply classification failed: %s", exc)
    return heuristic, None


def match_outreach(db: Session, msg: Message, from_addr: str) -> Outreach | None:
    ids = " ".join(filter(None, [msg.get("In-Reply-To"), msg.get("References")]))
    for mid in re.findall(r"<[^>]+>", ids):
        em = db.scalar(select(EmailMessage).where(EmailMessage.message_id == mid))
        if em:
            return em.outreach
    contact = db.scalar(select(Contact).where(Contact.email == from_addr).order_by(Contact.id.desc()))
    if contact:
        o = db.scalar(select(Outreach).where(Outreach.contact_id == contact.id).order_by(Outreach.created_at.desc()))
        if o:
            return o
    # A colleague at the same company replied from a different address.
    domain = registered_domain(from_addr)
    if domain:
        company = db.scalar(select(Company).where(Company.domain == domain))
        if company:
            return db.scalar(
                select(Outreach).where(Outreach.company_id == company.id).order_by(Outreach.created_at.desc())
            )
    return None


def apply_reply(db: Session, outreach: Outreach | None, classification: str, from_addr: str, summary: str | None) -> None:
    if classification == ReplyClass.BOUNCE:
        return  # handled separately per bounced recipient
    if classification == ReplyClass.UNSUBSCRIBE:
        suppress(db, email=from_addr, reason="unsubscribe", note="reply")
        if outreach:
            if outreach.contact.email != from_addr:
                suppress(db, email=outreach.contact.email, reason="unsubscribe", note=f"colleague {from_addr} asked")
            stop_outreach(db, outreach, OutreachStatus.STOPPED_UNSUBSCRIBED, "unsubscribe reply")
            outreach.project.lead_status = LeadStatus.UNSUBSCRIBED
        return
    if not outreach:
        return
    if classification == ReplyClass.OUT_OF_OFFICE:
        if outreach.status == OutreachStatus.ACTIVE and outreach.next_action_at:
            from datetime import timedelta

            outreach.next_action_at = max(outreach.next_action_at, utcnow()) + timedelta(days=5)
        return
    if classification == ReplyClass.NOT_INTERESTED:
        suppress(db, email=outreach.contact.email, reason="declined", note=summary)
        stop_outreach(db, outreach, OutreachStatus.STOPPED_DECLINED, "declined")
        outreach.project.lead_status = LeadStatus.NOT_INTERESTED
    else:
        stop_outreach(db, outreach, OutreachStatus.STOPPED_REPLIED, f"reply: {classification}")
        outreach.project.lead_status = (
            LeadStatus.INTERESTED if classification == ReplyClass.INTERESTED else LeadStatus.REPLIED
        )
    company = outreach.company.name if outreach.company else ""
    notify(
        f"Reply ({classification}) from {company}",
        [f"From: {from_addr}", f"Project: {outreach.project.title}", summary or ""],
        f"{settings.dashboard_url}/leads/{outreach.project_id}",
    )


def process_raw_email(db: Session, raw: bytes) -> InboundMessage | None:
    msg = email.message_from_bytes(raw, policy=default_policy)
    message_id = (msg.get("Message-ID") or "").strip()
    from_addr = parseaddr(msg.get("From", ""))[1].lower()
    if not message_id:
        message_id = f"<no-id-{hashlib.sha256(raw).hexdigest()[:32]}@local>"
    if db.scalar(select(InboundMessage.id).where(InboundMessage.message_id == message_id)):
        return None
    subject = str(msg.get("Subject") or "")
    try:
        received = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else utcnow()
    except (TypeError, ValueError):
        received = utcnow()

    if is_bounce(msg, from_addr):
        raw_text = raw.decode("utf-8", "ignore")
        rows = []
        for addr in bounced_recipients(msg, raw_text):
            if db.scalar(select(EmailMessage.id).where(EmailMessage.to_email == addr)):
                suppress(db, email=addr, reason="bounce")
                rows.append(addr)
        inbound = InboundMessage(message_id=message_id, from_email=from_addr, subject=subject[:1000],
                                 body_text=raw_text[:5000], classification=ReplyClass.BOUNCE,
                                 summary=f"Bounced: {', '.join(rows) or 'unknown recipient'}", received_at=received)
        db.add(inbound)
        return inbound

    body = strip_quoted(_text_body(msg))
    outreach = match_outreach(db, msg, from_addr)
    if not outreach and not _UNSUB_RE.search(f"{subject}\n{body}"):
        return None  # unrelated mail: leave it alone
    classification, summary = classify(subject, body)
    inbound = InboundMessage(
        message_id=message_id, outreach_id=outreach.id if outreach else None, from_email=from_addr,
        subject=subject[:1000], body_text=body[:10000], classification=classification, summary=summary,
        received_at=received,
    )
    db.add(inbound)
    apply_reply(db, outreach, classification, from_addr, summary)
    log_activity(db, "inbound", outreach.id if outreach else None, classification, from_email=from_addr)
    return inbound


def poll_inbox(db: Session, max_messages: int = 100) -> int:
    if not (settings.imap_host and settings.imap_user):
        return 0
    processed = 0
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as M:
        M.login(settings.imap_user, settings.imap_password)
        M.select(settings.imap_folder)
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK":
            return 0
        for num in data[0].split()[:max_messages]:
            typ, parts = M.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            try:
                result = process_raw_email(db, parts[0][1])
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("Failed to process inbound message %s", num)
                continue
            if result is not None:
                M.store(num, "+FLAGS", "\\Seen")  # only mark mail we handled
                processed += 1
    return processed
