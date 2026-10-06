from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- enums
# Stored as plain strings (no PG enum types) to keep migrations painless.


class Grade(StrEnum):
    HOT = "HOT"
    HIGH = "HIGH"
    WARM = "WARM"
    LOW = "LOW"


GRADE_RANK = {Grade.LOW: 0, Grade.WARM: 1, Grade.HIGH: 2, Grade.HOT: 3}


class SourceKind(StrEnum):
    NEWS_RSS = "news_rss"
    SEARCH = "search"
    LISTING = "listing"  # generic HTML notice/listing page (e.g. RIICO notices)
    TENDER_TABLE = "tender_table"  # GePNIC / CPPP style tender tables
    COMPANY_WEBSITE = "company_website"
    MANUAL = "manual"


class DocStatus(StrEnum):
    NEW = "new"
    FILTERED_OUT = "filtered_out"
    PENDING_AI = "pending_ai"
    CLASSIFIED = "classified"
    IRRELEVANT = "irrelevant"
    ERROR = "error"


class OpportunityKind(StrEnum):
    PRIVATE_PROJECT = "private_project"
    TENDER = "tender"


class LeadStatus(StrEnum):
    NEW = "new"
    NEEDS_CONTACT = "needs_contact"
    OUTREACH_QUEUED = "outreach_queued"
    CONTACTED = "contacted"
    REPLIED = "replied"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBED = "unsubscribed"
    WON = "won"
    LOST = "lost"
    DISQUALIFIED = "disqualified"


CLOSED_LEAD_STATUSES = {
    LeadStatus.NOT_INTERESTED,
    LeadStatus.UNSUBSCRIBED,
    LeadStatus.WON,
    LeadStatus.LOST,
    LeadStatus.DISQUALIFIED,
}


class OutreachStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED_REPLIED = "stopped_replied"
    STOPPED_DECLINED = "stopped_declined"
    STOPPED_UNSUBSCRIBED = "stopped_unsubscribed"
    STOPPED_BOUNCED = "stopped_bounced"
    STOPPED_MANUAL = "stopped_manual"


class EmailStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"
    DRY_RUN = "dry_run"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


PENDING_EMAIL_STATUSES = {EmailStatus.DRAFT, EmailStatus.APPROVED}


class RoleCategory(StrEnum):
    PROJECT_HEAD = "project_head"
    PURCHASE = "purchase"
    CIVIL_ENGINEERING = "civil_engineering"
    PLANT_HEAD = "plant_head"
    MANAGEMENT = "management"
    GENERIC = "generic"
    OTHER = "other"


class ReplyClass(StrEnum):
    INTERESTED = "interested"
    QUESTION = "question"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    OUT_OF_OFFICE = "out_of_office"
    BOUNCE = "bounce"
    OTHER = "other"


# ---------------------------------------------------------------- tables


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(200))
    cluster: Mapped[str | None] = mapped_column(String(50), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    size_tier: Mapped[str] = mapped_column(String(20), default="unknown")  # large | mid | small | unknown
    employee_estimate: Mapped[int | None] = mapped_column(Integer)
    is_quality: Mapped[bool | None] = mapped_column(Boolean)
    quality_reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    grade: Mapped[str] = mapped_column(String(10), default=Grade.LOW, index=True)
    monitor_website: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(50), default="discovered")
    notes: Mapped[str | None] = mapped_column(Text)
    last_monitored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    projects: Mapped[list["Project"]] = relationship(back_populates="company")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    items_last_run: Mapped[int] = mapped_column(Integer, default=0)


class Document(TimestampMixin, Base):
    """A fetched page / feed item / tender row — the raw evidence."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), index=True)
    source_kind: Mapped[str] = mapped_column(String(30))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    analysis_text: Mapped[str | None] = mapped_column(Text)  # new/changed text sent to AI
    content_hash: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default=DocStatus.NEW, index=True)
    prefilter_hits: Mapped[dict | None] = mapped_column(JSONType)
    ai_result: Mapped[dict | None] = mapped_column(JSONType)
    meta: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)


class Project(TimestampMixin, Base):
    """An opportunity: a private construction/expansion project or a public tender."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default=OpportunityKind.PRIVATE_PROJECT, index=True)
    title: Mapped[str] = mapped_column(Text)
    project_type: Mapped[str] = mapped_column(String(30), default="other")
    stage: Mapped[str] = mapped_column(String(30), default="unknown")
    location_text: Mapped[str | None] = mapped_column(Text)
    cluster: Mapped[str | None] = mapped_column(String(50), index=True)
    investment_inr_crore: Mapped[float | None] = mapped_column(Float)
    area_sqft: Mapped[float | None] = mapped_column(Float)
    timeline: Mapped[str | None] = mapped_column(Text)
    announcement_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    key_facts: Mapped[list] = mapped_column(JSONType, default=list)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ai_reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    grade: Mapped[str] = mapped_column(String(10), default=Grade.LOW, index=True)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONType)
    lead_status: Mapped[str] = mapped_column(String(30), default=LeadStatus.NEW, index=True)
    tender_ref: Mapped[str | None] = mapped_column(String(200))
    tender_authority: Mapped[str | None] = mapped_column(String(300))
    tender_closing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tender_value_inr: Mapped[float | None] = mapped_column(Float)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_grade: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company | None] = relationship(back_populates="projects")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Evidence.published_at.desc()"
    )
    outreaches: Mapped[list["Outreach"]] = relationship(back_populates="project")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("project_id", "url", name="uq_evidence_project_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="evidence")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("company_id", "email", name="uq_contact_company_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(300))
    role_category: Mapped[str] = mapped_column(String(30), default=RoleCategory.OTHER)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    email_source_url: Mapped[str | None] = mapped_column(Text)
    email_status: Mapped[str] = mapped_column(String(20), default="unknown")  # unknown|mx_ok|invalid|bounced
    phone: Mapped[str | None] = mapped_column(String(50))
    profile_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    is_generic: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Company] = relationship(back_populates="contacts")


class Outreach(TimestampMixin, Base):
    """An email sequence to one contact about one project."""

    __tablename__ = "outreaches"
    __table_args__ = (UniqueConstraint("project_id", "contact_id", name="uq_outreach_project_contact"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default=OutreachStatus.ACTIVE, index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=-1)  # last *sent* step; -1 = nothing sent
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    stopped_reason: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="outreaches")
    contact: Mapped[Contact] = relationship()
    company: Mapped[Company] = relationship()
    messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="outreach", order_by="EmailMessage.step", cascade="all, delete-orphan"
    )


class EmailMessage(TimestampMixin, Base):
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("outreach_id", "step", name="uq_email_outreach_step"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    outreach_id: Mapped[int] = mapped_column(ForeignKey("outreaches.id", ondelete="CASCADE"), index=True)
    step: Mapped[int] = mapped_column(Integer, default=0)  # 0 = initial, 1.. = follow-ups
    to_email: Mapped[str] = mapped_column(String(320), index=True)
    to_domain: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=EmailStatus.DRAFT, index=True)
    message_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(300))
    generated_by: Mapped[str] = mapped_column(String(20), default="ai")
    facts_used: Mapped[list] = mapped_column(JSONType, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    outreach: Mapped[Outreach] = relationship(back_populates="messages")


class InboundMessage(Base):
    __tablename__ = "inbound_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(300), unique=True)
    outreach_id: Mapped[int | None] = mapped_column(ForeignKey("outreaches.id", ondelete="SET NULL"), index=True)
    from_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Suppression(Base):
    """Global do-not-email list. Matched by exact email, or by domain when email is NULL."""

    __tablename__ = "suppressions"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    reason: Mapped[str] = mapped_column(String(30))  # unsubscribe | declined | bounce | manual
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


def log_activity(db, entity_type: str, entity_id: int | None, action: str, **detail) -> None:
    db.add(ActivityLog(entity_type=entity_type, entity_id=entity_id, action=action, detail=detail or None))
