"""End-to-end: document → AI verification → lead → contact → email → send → reply/unsubscribe."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.services.ai as ai_mod
from app.models import (
    Contact,
    DocStatus,
    Document,
    EmailMessage,
    EmailStatus,
    Grade,
    LeadStatus,
    Outreach,
    OutreachStatus,
    Project,
    Suppression,
)
from app.services import inbox, outreach, pipeline
from app.services.ai import GeneratedEmail, MentionedPerson, ProjectClassification
from app.services.collectors import RawItem
from app.services.runtime_settings import update_runtime
from app.services.suppression import make_unsubscribe_token

# Tue 11:00 IST — inside the default send window
SEND_TIME = datetime(2026, 10, 6, 5, 30, tzinfo=timezone.utc)


class FakeAI:
    enabled = True

    def __init__(self):
        self.calls = 0

    def classify_document(self, **kw):
        self.calls += 1
        return ProjectClassification(
            is_relevant=True, is_current=True, reason="New plant announced in Neemrana",
            opportunity_kind="private_project", company_name="Acme Auto Components Pvt Ltd",
            company_website="https://www.acmeauto.in", project_title="Acme new forging plant at Neemrana",
            project_type="factory", stage="land_acquired", location_text="Ghiloth, Neemrana", cluster="Neemrana",
            investment_inr_crore=450.0, area_sqft=None, expected_timeline="Production by 2027",
            announcement_date=(datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat(),
            tender_ref=None, tender_authority=None, tender_closing_date=None, tender_value_inr=None,
            key_facts=["Acme will invest Rs 450 crore in a new forging plant at Ghiloth, Neemrana",
                       "Production is targeted by 2027"],
            confidence=0.92,
            people_mentioned=[MentionedPerson(name="Rakesh Sharma", title="Head - Projects", email=None)],
        )

    def write_email(self, *, facts, sender, contact, followup_step=0, original_subject=None):
        if followup_step:
            return GeneratedEmail(subject=f"Re: {original_subject}", body="Dear Team,\n\nFollowing up briefly.",
                                  facts_referenced=[])
        return GeneratedEmail(
            subject="Acme's Rs 450 crore Neemrana plant – civil & PEB packages",
            body="Dear Projects Team,\n\nI read that Acme will invest Rs 450 crore in a new forging plant at Ghiloth.\n\n"
                 "Could we have a short call?",
            facts_referenced=facts["verified_facts"],
        )

    def classify_reply(self, subject, body):
        from app.services.ai import ReplyClassification

        return ReplyClassification(classification="interested", summary="Wants a call")


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(ai_mod, "_ai", fake)
    monkeypatch.setattr(pipeline, "notify", lambda *a, **k: None)
    monkeypatch.setattr(inbox, "notify", lambda *a, **k: None)
    return fake


class NoFetch:
    def get(self, *a, **k):
        from app.services.http import FetchError

        raise FetchError("network disabled in tests")


def _ingest(db):
    item = RawItem(url="https://news.example.com/acme-neemrana?utm_source=rss",
                   title="Acme Auto to set up Rs 450 crore forging plant in Neemrana",
                   snippet="Acme Auto Components will set up a new plant at Ghiloth industrial area, Neemrana.",
                   content_text="Acme Auto Components will set up a new plant at Ghiloth, Neemrana. Investment Rs 450 crore.",
                   published_at=datetime.now(timezone.utc) - timedelta(days=7))
    ids = pipeline.ingest_items(db, [item], source=None, source_kind="news_rss")
    db.commit()
    return ids


def _lead_with_contact(db):
    [doc_id] = _ingest(db)
    project = pipeline.process_document(db, db.get(Document, doc_id), NoFetch())
    from app.services.entities import add_named_contact, rescore_project

    add_named_contact(db, project.company, None, None, "projects@acmeauto.in", "https://www.acmeauto.in/contact")
    rescore_project(db, project)
    db.commit()
    return project


def test_ingest_dedupes_by_normalized_url(db, fake_ai):
    assert len(_ingest(db)) == 1
    assert _ingest(db) == []  # same URL (tracking params stripped) is ignored


def test_document_becomes_scored_lead_with_evidence(db, fake_ai):
    project = _lead_with_contact(db)
    assert project.company.name.startswith("Acme")
    assert project.company.domain == "acmeauto.in"
    assert project.cluster == "Neemrana" and project.is_current
    assert project.grade in (Grade.HOT, Grade.HIGH)
    assert len(project.evidence) == 1 and "450" in project.evidence[0].quote
    names = {c.name for c in project.company.contacts}
    assert "Rakesh Sharma" in names  # person named in the article
    doc = db.scalar(select(Document))
    assert doc.status == DocStatus.CLASSIFIED and doc.project_id == project.id


def test_same_project_from_second_source_merges(db, fake_ai):
    project = _lead_with_contact(db)
    item = RawItem(url="https://other.example.com/acme-plant", title="Acme forging plant Neemrana",
                   content_text="Acme new forging plant in Neemrana, construction to begin.")
    [doc_id] = pipeline.ingest_items(db, [item], source=None, source_kind="news_rss")
    p2 = pipeline.process_document(db, db.get(Document, doc_id), NoFetch())
    db.commit()
    assert p2.id == project.id
    assert len(p2.evidence) == 2
    assert db.query(Project).count() == 1


def test_auto_mode_sends_once_and_schedules_followup(db, fake_ai):
    update_runtime(db, {"email_send_mode": "auto", "auto_send_min_grade": "HIGH", "min_seconds_between_sends": 0})
    project = _lead_with_contact(db)
    o = outreach.plan_outreach(db, project)
    db.commit()
    assert o is not None
    msg = o.messages[0]
    assert msg.status == EmailStatus.APPROVED and msg.generated_by == "ai"
    assert "unsubscribe" in msg.body_text.lower() and "Plot 1, Bhiwadi" in msg.body_text

    # Never a second sequence for the same company.
    assert outreach.plan_outreach(db, project) is None

    sent = []
    r1 = outreach.process_send_queue(db, now=SEND_TIME, transport=sent.append)
    r2 = outreach.process_send_queue(db, now=SEND_TIME + timedelta(minutes=5), transport=sent.append)
    assert r1["sent"] == 1 and r2["sent"] == 0 and len(sent) == 1
    mime = sent[0]
    assert mime["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/u/" in mime["List-Unsubscribe"]
    db.refresh(o)
    assert o.current_step == 0 and o.next_action_at is not None
    assert project.lead_status == LeadStatus.CONTACTED

    # Follow-up drafted when due, threaded to the first email.
    o.next_action_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert outreach.schedule_followups(db) == 1
    assert outreach.schedule_followups(db) == 0  # no duplicate follow-up
    db.commit()
    f = db.scalar(select(EmailMessage).where(EmailMessage.step == 1))
    assert f.in_reply_to == msg.message_id and f.subject.startswith("Re:")


def test_send_window_and_limits(db, fake_ai):
    update_runtime(db, {"email_send_mode": "auto", "auto_send_min_grade": "HIGH", "daily_send_limit": 0})
    project = _lead_with_contact(db)
    outreach.plan_outreach(db, project)
    db.commit()
    assert outreach.process_send_queue(db, now=SEND_TIME, transport=lambda m: None)["reason"] == "daily limit reached"
    night = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)  # 01:30 IST
    assert outreach.process_send_queue(db, now=night, transport=lambda m: None)["reason"] == "outside send window"


def test_approval_mode_keeps_drafts(db, fake_ai):
    update_runtime(db, {"email_send_mode": "approval"})
    project = _lead_with_contact(db)
    o = outreach.plan_outreach(db, project)
    db.commit()
    assert o.messages[0].status == EmailStatus.DRAFT
    assert outreach.process_send_queue(db, now=SEND_TIME, transport=lambda m: None)["sent"] == 0


def _raw_reply(in_reply_to: str, body: str, frm="projects@acmeauto.in") -> bytes:
    return (
        f"From: Rakesh <{frm}>\r\nTo: sales@contractor.example.in\r\nSubject: Re: plant\r\n"
        f"Message-ID: <reply-{abs(hash(body))}@acmeauto.in>\r\nIn-Reply-To: {in_reply_to}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
    ).encode()


def _sent_outreach(db):
    update_runtime(db, {"email_send_mode": "auto", "auto_send_min_grade": "HIGH", "min_seconds_between_sends": 0})
    project = _lead_with_contact(db)
    o = outreach.plan_outreach(db, project)
    db.commit()
    outreach.process_send_queue(db, now=SEND_TIME, transport=lambda m: None)
    db.refresh(o)
    return o


def test_reply_stops_sequence(db, fake_ai):
    o = _sent_outreach(db)
    inbox.process_raw_email(db, _raw_reply(o.messages[0].message_id, "Yes, please call me tomorrow."))
    db.commit()
    db.refresh(o)
    assert o.status == OutreachStatus.STOPPED_REPLIED and o.next_action_at is None
    assert o.project.lead_status == LeadStatus.INTERESTED
    assert outreach.schedule_followups(db) == 0


def test_unsubscribe_reply_suppresses(db, fake_ai):
    o = _sent_outreach(db)
    inbox.process_raw_email(db, _raw_reply(o.messages[0].message_id, "Please remove me from your list. Unsubscribe."))
    db.commit()
    db.refresh(o)
    assert o.status == OutreachStatus.STOPPED_UNSUBSCRIBED
    assert db.scalar(select(Suppression).where(Suppression.email == "projects@acmeauto.in")).reason == "unsubscribe"
    assert db.scalar(select(Contact).where(Contact.email == "projects@acmeauto.in")).do_not_contact


def test_bounce_suppresses(db, fake_ai):
    o = _sent_outreach(db)
    raw = (
        "From: Mail Delivery Subsystem <mailer-daemon@google.com>\r\nSubject: Delivery Status Notification (Failure)\r\n"
        "Message-ID: <bounce1@google.com>\r\nContent-Type: text/plain\r\n\r\n"
        "Final-Recipient: rfc822; projects@acmeauto.in\r\nAction: failed\r\n"
    ).encode()
    inbox.process_raw_email(db, raw)
    db.commit()
    db.refresh(o)
    assert o.status == OutreachStatus.STOPPED_BOUNCED


def test_api_auth_leads_and_one_click_unsubscribe(db, fake_ai):
    from fastapi.testclient import TestClient

    from app.main import app

    _lead_with_contact(db)
    client = TestClient(app)
    assert client.get("/api/leads").status_code == 401
    token = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "pw"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    leads = client.get("/api/leads", headers=h).json()
    assert leads["total"] == 1
    row = leads["items"][0]
    assert row["company"]["name"].startswith("Acme") and row["top_evidence"]["url"].startswith("https://news.example.com")
    assert client.get(f"/api/leads/{row['id']}", headers=h).json()["key_facts"]
    assert client.get("/api/dashboard/summary", headers=h).status_code == 200
    assert client.put("/api/settings", json={"email_send_mode": "bogus"}, headers=h).status_code == 400

    tok = make_unsubscribe_token("projects@acmeauto.in")
    assert client.get(f"/u/{tok}").status_code == 200
    assert client.post(f"/u/{tok}", data={"List-Unsubscribe": "One-Click"}).status_code == 200
    assert client.post("/u/bad.token").status_code == 404
    db.expire_all()
    assert db.scalar(select(Suppression).where(Suppression.email == "projects@acmeauto.in"))
