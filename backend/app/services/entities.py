"""Company / project upserts with de-duplication, and (re)scoring."""

import logging
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Contact,
    Document,
    Evidence,
    Grade,
    LeadStatus,
    OpportunityKind,
    Project,
    log_activity,
    utcnow,
)
from app.services.ai import ProjectClassification
from app.services.extraction import normalize_company_name, parse_date, registered_domain
from app.services.scoring import score_company, score_project

log = logging.getLogger(__name__)

# Domains that are never a company's own website.
NON_COMPANY_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "indiamart.com", "justdial.com", "tradeindia.com", "zaubacorp.com", "tofler.in", "thecompanycheck.com",
    "economictimes.com", "indiatimes.com", "business-standard.com", "livemint.com", "moneycontrol.com",
    "thehindu.com", "hindustantimes.com", "google.com", "bing.com", "glassdoor.com", "naukri.com",
    "ambitionbox.com", "crunchbase.com", "bloomberg.com", "reuters.com", "gov.in", "nic.in", "riico.co.in",
}


def is_company_domain(domain: str | None) -> bool:
    return bool(domain) and domain not in NON_COMPANY_DOMAINS and not domain.endswith((".gov.in", ".nic.in"))


def find_company(db: Session, name: str | None = None, domain: str | None = None) -> Company | None:
    if domain:
        c = db.scalar(select(Company).where(Company.domain == domain))
        if c:
            return c
    if not name:
        return None
    norm = normalize_company_name(name)
    if not norm:
        return None
    c = db.scalar(select(Company).where(Company.normalized_name == norm))
    if c:
        return c
    # fuzzy fallback on names sharing the first token
    first = norm.split()[0]
    candidates = db.scalars(select(Company).where(Company.normalized_name.like(f"{first}%")).limit(50)).all()
    best, best_score = None, 0.0
    for cand in candidates:
        s = fuzz.token_sort_ratio(norm, cand.normalized_name)
        if s > best_score:
            best, best_score = cand, s
    return best if best_score >= 92 else None


def upsert_company(
    db: Session,
    name: str,
    *,
    website: str | None = None,
    cluster: str | None = None,
    industry: str | None = None,
    source: str = "discovered",
) -> Company:
    domain = registered_domain(website) if website else None
    if not is_company_domain(domain):
        domain, website = None, None
    company = find_company(db, name, domain)
    if company:
        if website and not company.website:
            if not domain or not db.scalar(select(Company.id).where(Company.domain == domain)):
                company.website, company.domain = website, domain
        company.cluster = company.cluster or cluster
        company.industry = company.industry or industry
        return company
    company = Company(
        name=name.strip()[:300],
        normalized_name=normalize_company_name(name)[:300] or name.lower()[:300],
        website=website,
        domain=domain,
        cluster=cluster,
        industry=industry,
        source=source,
    )
    db.add(company)
    db.flush()
    log_activity(db, "company", company.id, "created", source=source)
    return company


def find_similar_project(db: Session, company: Company | None, c: ProjectClassification) -> Project | None:
    q = select(Project).where(Project.created_at >= utcnow() - timedelta(days=540))
    if c.opportunity_kind == "tender" and c.tender_ref:
        p = db.scalar(select(Project).where(Project.tender_ref == c.tender_ref))
        if p:
            return p
    if company:
        q = q.where(Project.company_id == company.id)
    else:
        return None
    title = (c.project_title or "").lower()
    best, best_score = None, 0.0
    for p in db.scalars(q):
        s = fuzz.token_set_ratio(title, p.title.lower()) if title else 0
        if p.project_type == c.project_type:
            s += 10
        if p.cluster and p.cluster == c.cluster:
            s += 10
        if s > best_score:
            best, best_score = p, s
    return best if best_score >= 85 else None


def upsert_project_from_classification(
    db: Session, doc: Document, c: ProjectClassification
) -> tuple[Project, bool]:
    company = db.get(Company, doc.company_id) if doc.company_id else None
    if not company and c.company_name and c.opportunity_kind == "private_project":
        company = upsert_company(db, c.company_name, website=c.company_website, cluster=c.cluster, source="ai_extracted")
        doc.company_id = company.id

    project = find_similar_project(db, company, c)
    created = project is None
    if created:
        project = Project(
            company=company,
            kind=OpportunityKind.TENDER if c.opportunity_kind == "tender" else OpportunityKind.PRIVATE_PROJECT,
            title=(c.project_title or doc.title or "Untitled opportunity")[:500],
            lead_status=LeadStatus.NEW,
        )
        db.add(project)

    # Merge: newer / more specific facts win, never wipe known values with nulls.
    project.project_type = c.project_type if c.project_type != "other" or created else project.project_type
    if c.stage != "unknown":
        project.stage = c.stage
    for attr, val in (
        ("location_text", c.location_text),
        ("cluster", c.cluster),
        ("investment_inr_crore", c.investment_inr_crore),
        ("area_sqft", c.area_sqft),
        ("timeline", c.expected_timeline),
        ("tender_ref", c.tender_ref),
        ("tender_authority", c.tender_authority),
        ("tender_value_inr", c.tender_value_inr),
    ):
        if val not in (None, ""):
            setattr(project, attr, val)
    if c.announcement_date:
        project.announcement_date = parse_date(c.announcement_date) or project.announcement_date
    if c.tender_closing_date:
        project.tender_closing_at = parse_date(c.tender_closing_date) or project.tender_closing_at
    project.summary = c.reason
    project.ai_reason = c.reason
    facts = list(dict.fromkeys((project.key_facts or []) + c.key_facts))
    project.key_facts = facts[:12]
    project.is_relevant = c.is_relevant
    project.is_current = c.is_current
    project.ai_confidence = max(project.ai_confidence or 0.0, c.confidence) if not created else c.confidence
    project.last_evidence_at = doc.published_at or doc.fetched_at or utcnow()
    db.flush()

    ev = db.scalar(select(Evidence).where(Evidence.project_id == project.id, Evidence.url == doc.url))
    if not ev:
        project.evidence.append(
            Evidence(
                document_id=doc.id,
                url=doc.url,
                source_kind=doc.source_kind,
                title=doc.title,
                quote=" • ".join(c.key_facts[:4]) or (doc.snippet or "")[:500],
                published_at=doc.published_at,
            )
        )
    doc.project_id = project.id

    # People named in the source become (email-less unless printed) contacts.
    if company:
        for person in c.people_mentioned[:10]:
            add_named_contact(db, company, person.name, person.title, person.email, doc.url)

    db.flush()
    rescore_project(db, project)
    log_activity(db, "project", project.id, "created" if created else "evidence_added", url=doc.url)
    return project, created


def add_named_contact(db: Session, company: Company, name: str | None, title: str | None,
                      email: str | None, source_url: str | None, phone: str | None = None,
                      profile_url: str | None = None) -> Contact | None:
    from app.services.contacts import classify_role, check_email_domain

    if not name and not email:
        return None
    email = email.lower().strip() if email else None
    existing = None
    if email:
        existing = db.scalar(select(Contact).where(Contact.company_id == company.id, Contact.email == email))
    if not existing and name:
        for c in company.contacts:
            if c.name and fuzz.token_sort_ratio(c.name.lower(), name.lower()) >= 92:
                existing = c
                break
    if existing:
        existing.name = existing.name or name
        existing.title = existing.title or title
        existing.role_category = classify_role(existing.title, existing.email)
        existing.phone = existing.phone or phone
        existing.profile_url = existing.profile_url or profile_url
        if email and not existing.email:
            existing.email, existing.email_source_url = email, source_url
            existing.email_status = check_email_domain(email)
        return existing
    contact = Contact(
        company_id=company.id,
        name=name,
        title=title,
        role_category=classify_role(title, email),
        email=email,
        email_source_url=source_url if email else None,
        email_status=check_email_domain(email) if email else "unknown",
        phone=phone,
        profile_url=profile_url,
        source_url=source_url,
        is_generic=not bool(name),
        confidence=0.8 if email else 0.6,
    )
    company.contacts.append(contact)
    db.flush()
    return contact


def rescore_project(db: Session, project: Project) -> None:
    company = project.company if project.company_id else None
    contacts = company.contacts if company else []
    score, grade, breakdown = score_project(project, company, project.evidence, contacts)
    project.score, project.grade, project.score_breakdown = score, grade, breakdown
    if project.kind == OpportunityKind.PRIVATE_PROJECT and project.lead_status == LeadStatus.NEW and project.is_current \
            and project.is_relevant and grade in (Grade.HOT, Grade.HIGH):
        if not any(c.email and not c.do_not_contact for c in contacts):
            project.lead_status = LeadStatus.NEEDS_CONTACT
    if project.lead_status == LeadStatus.NEEDS_CONTACT and any(c.email and not c.do_not_contact for c in contacts):
        project.lead_status = LeadStatus.NEW
    if company:
        rescore_company(db, company)


def rescore_company(db: Session, company: Company) -> None:
    scores = [p.score for p in company.projects if p.is_current and p.is_relevant]
    company.score, company.grade = score_company(company, scores)


def rescore_all(db: Session) -> int:
    n = 0
    for project in db.scalars(select(Project).where(Project.created_at >= datetime.now(timezone.utc) - timedelta(days=730))):
        rescore_project(db, project)
        n += 1
    return n
