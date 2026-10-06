from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.routes.dashboard import _lead_query
from app.api.serializers import lead_detail, lead_row
from app.db import get_db
from app.models import Company, Contact, LeadStatus, Outreach, OutreachStatus, Project, log_activity
from app.services.entities import rescore_project
from app.services.outreach import _auto_approve, compose
from app.services.runtime_settings import get_runtime
from app.services.suppression import is_suppressed

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(require_user)])


@router.get("")
def list_leads(
    db: Session = Depends(get_db),
    grade: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    cluster: str | None = None,
    project_type: str | None = None,
    kind: str | None = None,
    current_only: bool = True,
    q: str | None = None,
    sort: str = "score",
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = _lead_query().outerjoin(Company, Project.company_id == Company.id)
    if grade:
        stmt = stmt.where(Project.grade.in_(grade))
    if status:
        stmt = stmt.where(Project.lead_status.in_(status))
    if cluster:
        stmt = stmt.where(Project.cluster == cluster)
    if project_type:
        stmt = stmt.where(Project.project_type == project_type)
    if kind:
        stmt = stmt.where(Project.kind == kind)
    if current_only:
        stmt = stmt.where(Project.is_current.is_(True), Project.is_relevant.is_(True))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Project.title).like(like), func.lower(Company.name).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = {
        "score": Project.score.desc(),
        "recent": Project.created_at.desc(),
        "evidence": Project.last_evidence_at.desc().nullslast(),
    }.get(sort, Project.score.desc())
    rows = db.scalars(stmt.order_by(order, Project.id.desc()).limit(limit).offset(offset)).unique().all()
    return {"total": total, "items": [lead_row(p) for p in rows]}


def _get(db: Session, lead_id: int) -> Project:
    p = db.scalar(_lead_query().where(Project.id == lead_id))
    if not p:
        raise HTTPException(404, "Lead not found")
    return p


@router.get("/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    return lead_detail(_get(db, lead_id))


class LeadPatch(BaseModel):
    lead_status: LeadStatus | None = None
    notes: str | None = None


@router.patch("/{lead_id}")
def update_lead(lead_id: int, body: LeadPatch, db: Session = Depends(get_db)):
    p = _get(db, lead_id)
    if body.lead_status:
        p.lead_status = body.lead_status
        if body.lead_status in (LeadStatus.DISQUALIFIED, LeadStatus.LOST, LeadStatus.WON, LeadStatus.NOT_INTERESTED):
            from app.services.suppression import stop_outreach

            for o in p.outreaches:
                stop_outreach(db, o, OutreachStatus.STOPPED_MANUAL, f"lead marked {body.lead_status}")
        log_activity(db, "project", p.id, "status_changed", status=body.lead_status)
    if body.notes is not None:
        p.notes = body.notes
    db.commit()
    return lead_detail(_get(db, lead_id))


@router.post("/{lead_id}/rescore")
def rescore(lead_id: int, db: Session = Depends(get_db)):
    p = _get(db, lead_id)
    rescore_project(db, p)
    db.commit()
    return lead_detail(_get(db, lead_id))


class StartOutreachIn(BaseModel):
    contact_id: int


@router.post("/{lead_id}/outreach")
def start_outreach(lead_id: int, body: StartOutreachIn, db: Session = Depends(get_db)):
    """Manually start a sequence to a chosen contact (bypasses grade threshold, not safety checks)."""
    p = _get(db, lead_id)
    contact = db.get(Contact, body.contact_id)
    if not contact or not p.company or contact.company_id != p.company_id:
        raise HTTPException(400, "Contact does not belong to this lead's company")
    if not contact.email or contact.do_not_contact or is_suppressed(db, contact.email):
        raise HTTPException(400, "Contact has no email or is suppressed")
    if db.scalar(select(Outreach.id).where(Outreach.project_id == p.id, Outreach.contact_id == contact.id)):
        raise HTTPException(409, "An outreach to this contact for this lead already exists")
    active = db.scalar(select(Outreach.id).where(
        Outreach.company_id == p.company_id, Outreach.status.in_([OutreachStatus.ACTIVE, OutreachStatus.PAUSED])))
    if active:
        raise HTTPException(409, "This company already has an active sequence")
    o = Outreach(project=p, company_id=p.company_id, contact=contact, status=OutreachStatus.ACTIVE)
    db.add(o)
    db.flush()
    msg = compose(db, o, 0)
    rt = get_runtime(db)
    if rt.email_send_mode == "dry_run":
        _auto_approve(msg, p, rt)  # manual starts in approval/auto mode still require explicit approval
    p.lead_status = LeadStatus.OUTREACH_QUEUED
    log_activity(db, "outreach", o.id, "started_manually", contact=contact.email)
    db.commit()
    return lead_detail(_get(db, lead_id))
