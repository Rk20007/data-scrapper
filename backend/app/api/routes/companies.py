import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_user
from app.api.serializers import company_full, contact_out, lead_row
from app.db import get_db
from app.models import Company, Contact, Outreach, Project
from app.services.contacts import check_email_domain, classify_role
from app.services.entities import upsert_company

router = APIRouter(tags=["companies"], dependencies=[Depends(require_user)])


@router.get("/companies")
def list_companies(
    db: Session = Depends(get_db),
    q: str | None = None,
    cluster: str | None = None,
    grade: list[str] = Query(default=[]),
    quality_only: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Company)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Company.name).like(like), func.lower(Company.domain).like(like)))
    if cluster:
        stmt = stmt.where(Company.cluster == cluster)
    if grade:
        stmt = stmt.where(Company.grade.in_(grade))
    if quality_only:
        stmt = stmt.where(Company.is_quality.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.options(selectinload(Company.contacts), selectinload(Company.projects))
        .order_by(Company.score.desc(), Company.name).limit(limit).offset(offset)
    ).all()
    items = []
    for c in rows:
        d = company_full(c)
        d["project_count"] = len(c.projects)
        d["contact_count"] = len(c.contacts)
        d["email_contact_count"] = sum(1 for x in c.contacts if x.email)
        items.append(d)
    return {"total": total, "items": items}


class CompanyIn(BaseModel):
    name: str
    website: str | None = None
    cluster: str | None = None
    industry: str | None = None
    notes: str | None = None


@router.post("/companies")
def create_company(body: CompanyIn, db: Session = Depends(get_db)):
    c = upsert_company(db, body.name, website=body.website, cluster=body.cluster, industry=body.industry, source="manual")
    if body.notes:
        c.notes = body.notes
    db.commit()
    return company_full(c)


@router.post("/companies/import")
async def import_companies(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """CSV with header: name,website,cluster,industry (only name required)."""
    raw = (await file.read()).decode("utf-8-sig", "ignore")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(400, "CSV must have a 'name' column")
    n = 0
    for row in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("name"):
            continue
        upsert_company(db, row["name"], website=row.get("website") or None, cluster=row.get("cluster") or None,
                       industry=row.get("industry") or None, source="import")
        n += 1
    db.commit()
    return {"imported": n}


@router.get("/companies/{company_id}")
def get_company(company_id: int, db: Session = Depends(get_db)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    projects = db.scalars(
        select(Project).where(Project.company_id == c.id).options(
            selectinload(Project.evidence), selectinload(Project.company).selectinload(Company.contacts),
            selectinload(Project.outreaches).selectinload(Outreach.messages),
            selectinload(Project.outreaches).selectinload(Outreach.contact),
        ).order_by(Project.score.desc())
    ).all()
    return {**company_full(c), "contacts": [contact_out(x) for x in c.contacts],
            "projects": [lead_row(p) for p in projects]}


class CompanyPatch(BaseModel):
    website: str | None = None
    cluster: str | None = None
    industry: str | None = None
    size_tier: str | None = None
    is_quality: bool | None = None
    monitor_website: bool | None = None
    notes: str | None = None


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyPatch, db: Session = Depends(get_db)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    data = body.model_dump(exclude_unset=True)
    if "website" in data:
        from app.services.extraction import registered_domain

        domain = registered_domain(data["website"]) if data["website"] else None
        if domain and db.scalar(select(Company.id).where(Company.domain == domain, Company.id != c.id)):
            raise HTTPException(409, "Another company already uses this domain")
        c.domain = domain
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    return company_full(c)


@router.post("/companies/{company_id}/enrich")
def enrich(company_id: int):
    from app.workers.tasks import enrich_company

    return {"task_id": enrich_company.delay(company_id).id}


@router.post("/companies/{company_id}/monitor")
def monitor(company_id: int):
    from app.workers.tasks import monitor_company

    return {"task_id": monitor_company.delay(company_id).id}


@router.post("/companies/{company_id}/assess")
def assess(company_id: int):
    from app.workers.tasks import assess_company

    return {"task_id": assess_company.delay(company_id).id}


# ---------------------------------------------------------------- contacts


class ContactIn(BaseModel):
    company_id: int
    name: str | None = None
    title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    source_url: str | None = None


@router.post("/contacts")
def create_contact(body: ContactIn, db: Session = Depends(get_db)):
    if not db.get(Company, body.company_id):
        raise HTTPException(404, "Company not found")
    email = str(body.email).lower() if body.email else None
    if email and db.scalar(select(Contact.id).where(Contact.company_id == body.company_id, Contact.email == email)):
        raise HTTPException(409, "Contact with this email already exists")
    c = Contact(
        company_id=body.company_id, name=body.name, title=body.title, email=email, phone=body.phone,
        role_category=classify_role(body.title, email), email_status=check_email_domain(email) if email else "unknown",
        email_source_url=body.source_url if email else None, source_url=body.source_url or "manual",
        is_generic=not body.name, confidence=0.9,
    )
    db.add(c)
    db.commit()
    return contact_out(c)


class ContactPatch(BaseModel):
    name: str | None = None
    title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    do_not_contact: bool | None = None


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactPatch, db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    data = body.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        data["email"] = str(data["email"]).lower()
        c.email_status = check_email_domain(data["email"])
        c.email_source_url = c.email_source_url or "manual"
    for k, v in data.items():
        setattr(c, k, v)
    c.role_category = classify_role(c.title, c.email)
    c.is_generic = not c.name
    db.commit()
    return contact_out(c)


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    if db.scalar(select(Outreach.id).where(Outreach.contact_id == c.id)):
        raise HTTPException(409, "Contact has outreach history; mark do_not_contact instead")
    db.delete(c)
    db.commit()
    return {"ok": True}
