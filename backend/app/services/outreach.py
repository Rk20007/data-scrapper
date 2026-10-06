"""Outreach planning, email composition, the rate-limited send queue and follow-ups.

Safety model
- An outreach is unique per (project, contact) and only one *active* outreach per company.
- Company cool-down: no new sequence to a company within N days of the last one.
- Each email row is unique per (outreach, step); its Message-ID is fixed before sending.
- Sending claims a row (approved → sending) in its own commit; a crash leaves it in
  "sending", which is never retried automatically — so an email is never sent twice.
- Suppression, contact flags and outreach state are re-checked immediately before send.
"""

import html
import logging
import smtplib
from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, formatdate, make_msgid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    CLOSED_LEAD_STATUSES,
    GRADE_RANK,
    Company,
    Contact,
    EmailMessage,
    EmailStatus,
    Grade,
    LeadStatus,
    OpportunityKind,
    Outreach,
    OutreachStatus,
    Project,
    log_activity,
    utcnow,
)
from app.services.ai import AIError, get_ai, unsupported_numbers
from app.services.contacts import pick_best_contact
from app.services.extraction import registered_domain
from app.services.notifications import _smtp_send
from app.services.runtime_settings import RuntimeSettings, get_runtime
from app.services.suppression import is_suppressed, stop_outreach, unsubscribe_url

log = logging.getLogger(__name__)

TZ = ZoneInfo(settings.timezone)


def _rank(grade: str) -> int:
    return GRADE_RANK.get(Grade(grade), 0)


# ---------------------------------------------------------------- composition


def _project_facts(project: Project) -> dict:
    company = project.company
    return {
        "company": company.name if company else None,
        "project": project.title,
        "project_type": project.project_type,
        "stage": project.stage,
        "location": project.location_text or project.cluster,
        "investment_inr_crore": project.investment_inr_crore,
        "area_sqft": project.area_sqft,
        "timeline": project.timeline,
        "verified_facts": project.key_facts,
        "source_types": sorted({e.source_kind for e in project.evidence}),
    }


def _sender_profile() -> dict:
    return {
        "name": settings.sender_name,
        "title": settings.sender_title,
        "company": settings.sender_company,
        "offering": settings.sender_offering,
        "verified_credentials": settings.sender_credentials,
        "website": settings.sender_website,
    }


def _contact_profile(contact: Contact) -> dict:
    return {
        "name": contact.name if not contact.is_generic else None,
        "title": contact.title,
        "role": contact.role_category,
    }


def _greeting(contact: Contact) -> str:
    if contact.name and not contact.is_generic:
        return f"Dear {contact.name},"
    return {
        "purchase": "Dear Purchase Team,",
        "project_head": "Dear Projects Team,",
        "civil_engineering": "Dear Engineering Team,",
        "plant_head": "Dear Plant Head,",
    }.get(contact.role_category, "Dear Sir/Madam,")


def template_email(project: Project, contact: Contact, step: int, original_subject: str | None) -> tuple[str, str]:
    """Deterministic fallback used when AI is unavailable or its draft fails validation."""
    company = project.company.name if project.company else "your company"
    place = project.cluster or project.location_text or "the region"
    possessive = "'" if company.endswith("s") else "'s"
    if step == 0:
        subject = f"{company}: {project.project_type.replace('_', ' ')} project in {place}"[:70]
        fact = project.key_facts[0] if project.key_facts else project.title
        body = (
            f"{_greeting(contact)}\n\n"
            f"I came across public information about {company}{possessive} project in {place}: {fact}\n\n"
            f"{settings.sender_company} works on {settings.sender_offering} in the Bhiwadi–Neemrana belt. "
            f"If the construction packages for this project are still being planned, we would welcome the chance to "
            f"share relevant work and a budgetary approach.\n\n"
            f"Would a 15-minute call next week be useful?"
        )
    else:
        subject = f"Re: {original_subject}" if original_subject else f"Re: {company} project in {place}"
        final = step >= settings.max_followups
        body = (
            f"{_greeting(contact)}\n\n"
            f"Following up on my earlier note about the {place} project. If someone else handles civil/PEB "
            f"packages, I would be grateful if you could point me to them."
            + ("\n\nI will not follow up further — thank you for your time." if final else "")
        )
    return subject, body


def _signature_and_footer(to_email: str) -> tuple[str, str]:
    sig_lines = [x for x in (settings.sender_name, settings.sender_title, settings.sender_company,
                             settings.sender_phone, settings.sender_website) if x]
    signature = "\n".join(["Regards,"] + sig_lines)
    footer = (
        f"\n\n--\n{settings.sender_company}"
        + (f", {settings.sender_address}" if settings.sender_address else "")
        + "\nYou are receiving this one-to-one business email because your company's project was publicly reported. "
        f"To stop receiving emails from us, reply 'unsubscribe' or visit: {unsubscribe_url(to_email)}"
    )
    return signature, footer


def compose(db: Session, outreach: Outreach, step: int) -> EmailMessage:
    project, contact = outreach.project, outreach.contact
    first = next((m for m in outreach.messages if m.step == 0), None)
    original_subject = first.subject if first else None
    facts = _project_facts(project)

    subject = body = None
    generated_by = "template"
    ai = get_ai()
    if ai.enabled:
        allowed = " ".join(
            [str(v) for v in facts.values() if v]
            + [str(v) for v in _sender_profile().values() if v]
            + [original_subject or ""]
        )
        for _ in range(2):
            try:
                draft = ai.write_email(
                    facts=facts, sender=_sender_profile(), contact=_contact_profile(contact),
                    followup_step=step, original_subject=original_subject,
                )
            except AIError as exc:
                log.warning("AI email generation failed: %s", exc)
                break
            bad = unsupported_numbers(f"{draft.subject} {draft.body}", allowed)
            if bad:
                log.warning("Rejected AI draft with unsupported numbers %s", bad)
                continue
            subject, body, generated_by = draft.subject.strip(), draft.body.strip(), "ai"
            break
    if not body:
        subject, body = template_email(project, contact, step, original_subject)
    if step > 0 and original_subject and not subject.lower().startswith("re:"):
        subject = f"Re: {original_subject}"

    signature, footer = _signature_and_footer(contact.email)
    msg = EmailMessage(
        outreach=outreach,
        step=step,
        to_email=contact.email,
        to_domain=registered_domain(contact.email) or contact.email.split("@")[-1],
        subject=subject[:300],
        body_text=f"{body}\n\n{signature}{footer}",
        status=EmailStatus.DRAFT,
        in_reply_to=first.message_id if (step > 0 and first) else None,
        generated_by=generated_by,
        facts_used=project.key_facts,
    )
    db.add(msg)
    db.flush()
    return msg


def _auto_approve(msg: EmailMessage, project: Project, rt: RuntimeSettings) -> None:
    if rt.email_send_mode == "dry_run" or (
        rt.email_send_mode == "auto" and _rank(project.grade) >= _rank(rt.auto_send_min_grade)
    ):
        msg.status = EmailStatus.APPROVED
        msg.approved_at = utcnow()


# ---------------------------------------------------------------- planning


def plan_outreach(db: Session, project: Project, rt: RuntimeSettings | None = None) -> Outreach | None:
    rt = rt or get_runtime(db)
    if project.kind != OpportunityKind.PRIVATE_PROJECT or not (project.is_current and project.is_relevant):
        return None
    if _rank(project.grade) < _rank(rt.outreach_min_grade) or project.lead_status in CLOSED_LEAD_STATUSES:
        return None
    company: Company | None = project.company
    if not company:
        return None

    busy = db.scalar(
        select(Outreach.id).where(
            Outreach.company_id == company.id,
            (Outreach.status.in_([OutreachStatus.ACTIVE, OutreachStatus.PAUSED]))
            | (Outreach.created_at >= utcnow() - timedelta(days=rt.company_cooldown_days)),
        ).limit(1)
    )
    if busy:
        return None

    contact = pick_best_contact(company, lambda e: is_suppressed(db, e))
    if not contact:
        if project.lead_status == LeadStatus.NEW:
            project.lead_status = LeadStatus.NEEDS_CONTACT
        return None
    if db.scalar(select(Outreach.id).where(Outreach.project_id == project.id, Outreach.contact_id == contact.id)):
        return None

    outreach = Outreach(project=project, company_id=company.id, contact=contact, status=OutreachStatus.ACTIVE)
    db.add(outreach)
    db.flush()
    msg = compose(db, outreach, 0)
    _auto_approve(msg, project, rt)
    project.lead_status = LeadStatus.OUTREACH_QUEUED
    log_activity(db, "outreach", outreach.id, "planned", project_id=project.id, contact=contact.email, status=msg.status)
    return outreach


def plan_outreach_batch(db: Session, limit: int = 25) -> int:
    rt = get_runtime(db)
    min_rank = _rank(rt.outreach_min_grade)
    grades = [g for g in Grade if GRADE_RANK[g] >= min_rank]
    projects = db.scalars(
        select(Project)
        .where(
            Project.kind == OpportunityKind.PRIVATE_PROJECT,
            Project.is_current.is_(True),
            Project.is_relevant.is_(True),
            Project.grade.in_(grades),
            Project.lead_status.in_([LeadStatus.NEW, LeadStatus.NEEDS_CONTACT]),
        )
        .order_by(Project.score.desc())
        .limit(limit)
    ).all()
    n = 0
    for p in projects:
        if plan_outreach(db, p, rt):
            n += 1
    return n


def schedule_followups(db: Session) -> int:
    rt = get_runtime(db)
    due = db.scalars(
        select(Outreach).where(
            Outreach.status == OutreachStatus.ACTIVE,
            Outreach.next_action_at.is_not(None),
            Outreach.next_action_at <= utcnow(),
        )
    ).all()
    n = 0
    for o in due:
        next_step = o.current_step + 1
        if next_step > rt.max_followups:
            o.status, o.next_action_at = OutreachStatus.COMPLETED, None
            continue
        if any(m.step == next_step for m in o.messages):  # duplicate protection
            o.next_action_at = None
            continue
        if is_suppressed(db, o.contact.email) or o.contact.do_not_contact:
            stop_outreach(db, o, OutreachStatus.STOPPED_MANUAL, "contact suppressed")
            continue
        msg = compose(db, o, next_step)
        _auto_approve(msg, o.project, rt)
        o.next_action_at = None  # re-armed after this step is sent
        n += 1
    return n


# ---------------------------------------------------------------- sending


def in_send_window(now: datetime, rt: RuntimeSettings) -> bool:
    local = now.astimezone(TZ)
    if not rt.send_on_weekends and local.weekday() >= 5:
        return False
    return rt.send_window_start_hour <= local.hour < rt.send_window_end_hour


def _sent_status(rt: RuntimeSettings) -> str:
    return EmailStatus.DRY_RUN if rt.email_send_mode == "dry_run" else EmailStatus.SENT


def build_mime(msg: EmailMessage) -> MimeMessage:
    m = MimeMessage()
    from_addr = settings.sender_email or settings.smtp_user
    m["From"] = formataddr((settings.sender_name or settings.sender_company, from_addr))
    m["To"] = msg.to_email
    m["Subject"] = msg.subject
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = msg.message_id
    if settings.reply_to:
        m["Reply-To"] = settings.reply_to
    if msg.in_reply_to:
        m["In-Reply-To"] = msg.in_reply_to
        m["References"] = msg.in_reply_to
    unsub = [f"<{unsubscribe_url(msg.to_email)}>"]
    mailto = settings.unsubscribe_mailto or settings.reply_to or from_addr
    if mailto:
        unsub.insert(0, f"<mailto:{mailto}?subject=unsubscribe>")
    m["List-Unsubscribe"] = ", ".join(unsub)
    m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    m.set_content(msg.body_text)
    html_body = html.escape(msg.body_text).replace("\n", "<br>\n")
    url = unsubscribe_url(msg.to_email)
    html_body = html_body.replace(html.escape(url), f'<a href="{html.escape(url)}">{html.escape(url)}</a>')
    m.add_alternative(f'<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">{html_body}</div>',
                      subtype="html")
    return m


def preflight(db: Session, msg: EmailMessage, rt: RuntimeSettings, now: datetime) -> str | None:
    """Return a reason to skip this message, or None if it may be sent."""
    o = msg.outreach
    if o.status != OutreachStatus.ACTIVE:
        return f"outreach {o.status}"
    if o.contact.do_not_contact or o.contact.email_status in ("invalid", "bounced"):
        return "contact not contactable"
    if o.contact.email != msg.to_email:
        return "contact email changed"
    if is_suppressed(db, msg.to_email):
        return "suppressed"
    if o.project.lead_status in CLOSED_LEAD_STATUSES:
        return f"lead {o.project.lead_status}"
    if msg.step != o.current_step + 1:
        return f"out of sequence (step {msg.step}, last sent {o.current_step})"
    dup = db.scalar(
        select(func.count(EmailMessage.id)).where(
            EmailMessage.outreach_id == o.id,
            EmailMessage.step == msg.step,
            EmailMessage.status.in_([EmailStatus.SENT, EmailStatus.SENDING, EmailStatus.DRY_RUN]),
            EmailMessage.id != msg.id,
        )
    )
    if dup:
        return "duplicate step"
    return None


def _domain_sent_today(db: Session, domain: str, start: datetime, status: str) -> int:
    return db.scalar(
        select(func.count(EmailMessage.id)).where(
            EmailMessage.to_domain == domain, EmailMessage.status == status, EmailMessage.sent_at >= start
        )
    ) or 0


def process_send_queue(db: Session, now: datetime | None = None, transport=None) -> dict:
    """Send at most one email per call. Intended to run every minute from Celery beat."""
    rt = get_runtime(db)
    now = now or utcnow()
    if rt.email_send_mode != "dry_run":
        if not settings.smtp_host:
            return {"sent": 0, "reason": "smtp not configured"}
        if not in_send_window(now, rt):
            return {"sent": 0, "reason": "outside send window"}

    status = _sent_status(rt)
    local_midnight = datetime.combine(now.astimezone(TZ).date(), time.min, tzinfo=TZ)
    sent_today = db.scalar(select(func.count(EmailMessage.id)).where(
        EmailMessage.status == status, EmailMessage.sent_at >= local_midnight)) or 0
    sent_hour = db.scalar(select(func.count(EmailMessage.id)).where(
        EmailMessage.status == status, EmailMessage.sent_at >= now - timedelta(hours=1))) or 0
    if sent_today >= rt.daily_send_limit:
        return {"sent": 0, "reason": "daily limit reached"}
    if sent_hour >= rt.hourly_send_limit:
        return {"sent": 0, "reason": "hourly limit reached"}
    last = db.scalar(select(func.max(EmailMessage.sent_at)).where(EmailMessage.status == status))
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < rt.min_seconds_between_sends:
            return {"sent": 0, "reason": "spacing"}

    candidates = db.scalars(
        select(EmailMessage)
        .where(
            EmailMessage.status == EmailStatus.APPROVED,
            (EmailMessage.scheduled_at.is_(None)) | (EmailMessage.scheduled_at <= now),
        )
        .order_by(EmailMessage.step, EmailMessage.approved_at, EmailMessage.id)
        .limit(10)
        .with_for_update(skip_locked=True)
    ).all()

    for msg in candidates:
        reason = preflight(db, msg, rt, now)
        if reason:
            if reason.startswith("out of sequence"):
                continue  # wait for the earlier step
            msg.status, msg.error = EmailStatus.SKIPPED, reason
            log_activity(db, "email", msg.id, "skipped", reason=reason)
            db.commit()
            continue
        if _domain_sent_today(db, msg.to_domain, local_midnight, status) >= rt.per_domain_daily_limit:
            continue

        # Claim the row before talking to SMTP.
        if not msg.message_id:
            domain = (settings.sender_email or settings.smtp_user or "localhost").split("@")[-1]
            msg.message_id = make_msgid(idstring=f"lead{msg.outreach_id}s{msg.step}", domain=domain)
        msg.status = EmailStatus.SENDING
        msg.attempts += 1
        db.commit()

        try:
            mime = build_mime(msg)
            if rt.email_send_mode == "dry_run":
                log.info("DRY RUN email to %s: %s", msg.to_email, msg.subject)
            else:
                (transport or _smtp_send)(mime)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            msg.status, msg.error = EmailStatus.FAILED, str(exc)[:1000]
            db.commit()
            return {"sent": 0, "failed": msg.id}
        except Exception as exc:  # noqa: BLE001 — transient: retry up to 3 attempts
            msg.status = EmailStatus.APPROVED if msg.attempts < 3 else EmailStatus.FAILED
            msg.error = str(exc)[:1000]
            msg.scheduled_at = now + timedelta(minutes=15 * msg.attempts)
            db.commit()
            return {"sent": 0, "error": str(exc)}

        _mark_sent(db, msg, status, now, rt)
        db.commit()
        return {"sent": 1, "email_id": msg.id, "status": status}
    return {"sent": 0, "reason": "nothing to send"}


def _mark_sent(db: Session, msg: EmailMessage, status: str, now: datetime, rt: RuntimeSettings) -> None:
    msg.status, msg.sent_at, msg.error = status, now, None
    o = msg.outreach
    o.current_step = msg.step
    if msg.step < rt.max_followups and msg.step < len(rt.followup_delays_days):
        o.next_action_at = now + timedelta(days=rt.followup_delays_days[msg.step])
    else:
        o.status, o.next_action_at = OutreachStatus.COMPLETED, None
    if o.project.lead_status in (LeadStatus.NEW, LeadStatus.NEEDS_CONTACT, LeadStatus.OUTREACH_QUEUED):
        o.project.lead_status = LeadStatus.CONTACTED
    log_activity(db, "email", msg.id, status, to=msg.to_email, step=msg.step)


def reap_stuck_sending(db: Session, minutes: int = 30) -> int:
    """Rows stuck in 'sending' (worker crash) are marked failed — never resent automatically."""
    stuck = db.scalars(
        select(EmailMessage).where(
            EmailMessage.status == EmailStatus.SENDING, EmailMessage.updated_at < utcnow() - timedelta(minutes=minutes)
        )
    ).all()
    for m in stuck:
        m.status = EmailStatus.FAILED
        m.error = "Worker stopped mid-send; check the sent folder before re-approving."
    return len(stuck)

