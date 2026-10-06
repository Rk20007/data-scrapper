from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models import Grade
from app.services.ai import unsupported_numbers
from app.services.contacts import classify_role, is_outreach_mailbox
from app.services.extraction import (
    detect_cluster,
    find_emails,
    new_lines,
    normalize_company_name,
    normalize_url,
    prefilter,
    registered_domain,
)
from app.services.inbox import heuristic_classify, strip_quoted
from app.services.scoring import grade_for, score_project
from app.services.suppression import make_unsubscribe_token, verify_unsubscribe_token

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def _project(**kw):
    base = dict(project_type="factory", stage="planning", cluster="Bhiwadi", investment_inr_crore=250.0,
                area_sqft=None, tender_value_inr=None, kind="private_project", is_relevant=True, is_current=True,
                ai_confidence=0.9, announcement_date=NOW - timedelta(days=10), last_evidence_at=None,
                tender_closing_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _contact(**kw):
    base = dict(email="projects@acme.in", do_not_contact=False, email_status="mx_ok",
                role_category="project_head", is_generic=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_strong_lead_is_hot():
    company = SimpleNamespace(size_tier="large", is_quality=True)
    ev = [SimpleNamespace(source_kind="news_rss", published_at=NOW - timedelta(days=5))]
    score, grade, b = score_project(_project(), company, ev, [_contact()], now=NOW)
    assert grade == Grade.HOT and score >= 75, b


def test_stale_or_irrelevant_capped_low():
    company = SimpleNamespace(size_tier="large", is_quality=True)
    ev = [SimpleNamespace(source_kind="news_rss", published_at=NOW)]
    for p in (_project(is_current=False), _project(is_relevant=False)):
        score, grade, _ = score_project(p, company, ev, [_contact()], now=NOW)
        assert grade == Grade.LOW and score <= 30


def test_closed_tender_capped():
    p = _project(kind="tender", stage="tendering", tender_closing_at=NOW - timedelta(days=1), tender_value_inr=5e7)
    score, grade, b = score_project(p, None, [SimpleNamespace(source_kind="tender_table", published_at=NOW)], [], now=NOW)
    assert score <= 20 and b["gate"] == "tender closed"


def test_grade_thresholds():
    assert [grade_for(s) for s in (90, 75, 60, 40, 10)] == ["HOT", "HOT", "HIGH", "WARM", "LOW"]


def test_prefilter_requires_project_and_location():
    assert prefilter("XYZ Ltd to set up new plant in Neemrana with Rs 300 crore").passed
    assert not prefilter("XYZ Ltd to set up new plant in Pune").passed
    assert prefilter("XYZ Ltd expansion announced", location_known=True).passed
    assert not prefilter("Quarterly results announced for Bhiwadi unit").passed


def test_cluster_detection_aliases():
    assert detect_cluster("Plot SP-12, Ghiloth Industrial Area") == "Neemrana"
    assert detect_cluster("Chopanki, Bhiwadi") == "Bhiwadi"
    assert detect_cluster("Jaipur") is None


def test_text_helpers():
    assert normalize_company_name("Acme Auto Components Pvt. Ltd.") == "acme auto components"
    assert registered_domain("https://www.acme.co.in/about") == "acme.co.in"
    assert registered_domain("info@mail.acme.co.in") == "acme.co.in"
    assert normalize_url("https://Ex.com/a/?utm_source=x&id=2#top") == "https://ex.com/a?id=2"
    assert find_emails("write to purchase [at] acme [dot] in or logo@2x.png") == {"purchase@acme.in"}
    assert new_lines("a\nb", "a\nb\nc") == "c"


def test_roles_and_mailboxes():
    assert classify_role("Head - Projects & Capex") == "project_head"
    assert classify_role("AGM Purchase") == "purchase"
    assert classify_role("Plant Head, Neemrana") == "plant_head"
    assert classify_role(None, "procurement@acme.in") == "purchase"
    assert classify_role(None, "info@acme.in") == "generic"
    assert not is_outreach_mailbox("hr@acme.in") and not is_outreach_mailbox("careers@acme.in")
    assert is_outreach_mailbox("purchase@acme.in")


def test_unsubscribe_token_roundtrip_and_tamper():
    t = make_unsubscribe_token("A@Acme.in")
    assert verify_unsubscribe_token(t) == "a@acme.in"
    assert verify_unsubscribe_token(t[:-2] + "xx") is None
    assert verify_unsubscribe_token("garbage") is None


def test_hallucinated_numbers_detected():
    facts = "Rs 450 crore plant, 2,00,000 sq ft, phase 1 by 2027"
    assert unsupported_numbers("Your 450 crore plant due 2027", facts) == []
    assert unsupported_numbers("We built 35 factories", facts) == ["35"]


def test_reply_heuristics():
    assert heuristic_classify("Re: x", "Please unsubscribe me") == "unsubscribe"
    assert heuristic_classify("Automatic reply", "I am out of office") == "out_of_office"
    assert heuristic_classify("Re: x", "We are not interested, thanks") == "not_interested"
    assert strip_quoted("Sounds good\n\nOn Mon, X wrote:\n> old") == "Sounds good"
