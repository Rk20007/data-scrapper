"""Model → JSON dict helpers shared by the routes."""

from app.models import Company, Contact, EmailMessage, Evidence, Outreach, Project, Source


def company_brief(c: Company | None) -> dict | None:
    if not c:
        return None
    return {"id": c.id, "name": c.name, "domain": c.domain, "website": c.website, "cluster": c.cluster,
            "size_tier": c.size_tier, "is_quality": c.is_quality, "grade": c.grade, "score": c.score}


def company_full(c: Company) -> dict:
    return {
        **company_brief(c),
        "industry": c.industry, "address": c.address, "employee_estimate": c.employee_estimate,
        "quality_reason": c.quality_reason, "monitor_website": c.monitor_website, "source": c.source,
        "notes": c.notes, "last_monitored_at": c.last_monitored_at, "last_enriched_at": c.last_enriched_at,
        "created_at": c.created_at,
    }


def contact_out(c: Contact) -> dict:
    return {
        "id": c.id, "company_id": c.company_id, "name": c.name, "title": c.title, "role_category": c.role_category,
        "email": c.email, "email_status": c.email_status, "email_source_url": c.email_source_url, "phone": c.phone,
        "profile_url": c.profile_url, "source_url": c.source_url, "is_generic": c.is_generic,
        "confidence": c.confidence, "do_not_contact": c.do_not_contact,
    }


def evidence_out(e: Evidence) -> dict:
    return {"id": e.id, "url": e.url, "source_kind": e.source_kind, "title": e.title, "quote": e.quote,
            "published_at": e.published_at, "created_at": e.created_at}


def email_out(m: EmailMessage, with_body: bool = True) -> dict:
    d = {
        "id": m.id, "outreach_id": m.outreach_id, "step": m.step, "to_email": m.to_email, "subject": m.subject,
        "status": m.status, "generated_by": m.generated_by, "scheduled_at": m.scheduled_at,
        "approved_at": m.approved_at, "sent_at": m.sent_at, "error": m.error, "attempts": m.attempts,
        "created_at": m.created_at,
    }
    if with_body:
        d["body_text"] = m.body_text
        d["facts_used"] = m.facts_used
    return d


def outreach_out(o: Outreach) -> dict:
    return {
        "id": o.id, "project_id": o.project_id, "company_id": o.company_id, "status": o.status,
        "current_step": o.current_step, "next_action_at": o.next_action_at, "stopped_reason": o.stopped_reason,
        "contact": contact_out(o.contact), "messages": [email_out(m) for m in o.messages], "created_at": o.created_at,
    }


def _latest_email_status(p: Project) -> str | None:
    msgs = [m for o in p.outreaches for m in o.messages]
    if not msgs:
        return None
    return max(msgs, key=lambda m: (m.updated_at or m.created_at)).status


def _primary_contact(p: Project) -> Contact | None:
    for o in sorted(p.outreaches, key=lambda o: o.created_at, reverse=True):
        return o.contact
    if p.company:
        from app.services.contacts import ROLE_PRIORITY

        reachable = [c for c in p.company.contacts if not c.do_not_contact]
        if reachable:
            def key(c):
                try:
                    r = ROLE_PRIORITY.index(c.role_category)
                except ValueError:
                    r = 99
                return (0 if c.email else 1, r)

            return sorted(reachable, key=key)[0]
    return None


def lead_row(p: Project) -> dict:
    ev = p.evidence[0] if p.evidence else None
    contact = _primary_contact(p)
    return {
        "id": p.id, "title": p.title, "kind": p.kind, "project_type": p.project_type, "stage": p.stage,
        "cluster": p.cluster, "location_text": p.location_text, "investment_inr_crore": p.investment_inr_crore,
        "score": p.score, "grade": p.grade, "lead_status": p.lead_status, "is_current": p.is_current,
        "is_relevant": p.is_relevant, "ai_confidence": p.ai_confidence, "first_seen_at": p.first_seen_at,
        "last_evidence_at": p.last_evidence_at, "tender_closing_at": p.tender_closing_at,
        "tender_authority": p.tender_authority,
        "company": company_brief(p.company),
        "evidence_count": len(p.evidence),
        "top_evidence": evidence_out(ev) if ev else None,
        "contact": contact_out(contact) if contact else None,
        "email_status": _latest_email_status(p),
        "outreach_status": p.outreaches[-1].status if p.outreaches else None,
    }


def lead_detail(p: Project) -> dict:
    return {
        **lead_row(p),
        "summary": p.summary, "ai_reason": p.ai_reason, "key_facts": p.key_facts, "area_sqft": p.area_sqft,
        "timeline": p.timeline, "announcement_date": p.announcement_date, "score_breakdown": p.score_breakdown,
        "tender_ref": p.tender_ref, "tender_value_inr": p.tender_value_inr, "notes": p.notes,
        "evidence": [evidence_out(e) for e in p.evidence],
        "contacts": [contact_out(c) for c in p.company.contacts] if p.company else [],
        "outreaches": [outreach_out(o) for o in p.outreaches],
    }


def source_out(s: Source) -> dict:
    return {
        "id": s.id, "name": s.name, "kind": s.kind, "url": s.url, "config": s.config, "enabled": s.enabled,
        "interval_minutes": s.interval_minutes, "last_run_at": s.last_run_at, "last_success_at": s.last_success_at,
        "last_status": s.last_status, "last_error": s.last_error, "items_last_run": s.items_last_run,
    }
