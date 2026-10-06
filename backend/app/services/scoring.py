"""Transparent, rule-based lead scoring (0-100) → HOT / HIGH / WARM / LOW.

AI decides *facts* (relevance, stage, size); this module turns facts into a score so
operators can see exactly why a lead is ranked where it is."""

from datetime import datetime, timezone

from app.models import Grade, OpportunityKind, RoleCategory

TYPE_POINTS = {
    "factory": 20, "peb": 20, "warehouse": 18, "expansion": 18, "epc": 17,
    "industrial_park": 16, "civil": 15, "construction": 14, "other": 5,
}
STAGE_POINTS = {
    "tendering": 22, "approved": 20, "land_acquired": 20, "planning": 18, "announced": 15,
    "under_construction": 10, "unknown": 6, "completed": 0,
}
SOURCE_POINTS = {"tender_table": 8, "listing": 8, "company_website": 8, "news_rss": 6, "search": 3, "manual": 5}
SIZE_POINTS = {"large": 10, "mid": 6, "small": 2, "unknown": 3}
DECISION_ROLES = {RoleCategory.PROJECT_HEAD, RoleCategory.PURCHASE, RoleCategory.CIVIL_ENGINEERING,
                  RoleCategory.PLANT_HEAD, RoleCategory.MANAGEMENT}

THRESHOLDS = [(75, Grade.HOT), (55, Grade.HIGH), (35, Grade.WARM)]


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def grade_for(score: int) -> Grade:
    for threshold, grade in THRESHOLDS:
        if score >= threshold:
            return grade
    return Grade.LOW


def _recency_points(latest: datetime | None, now: datetime) -> int:
    if not latest:
        return 4
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    days = (now - latest).days
    if days <= 30:
        return 15
    if days <= 90:
        return 12
    if days <= 180:
        return 8
    if days <= 365:
        return 4
    return 0


def _size_points(investment_cr: float | None, area_sqft: float | None, tender_value_inr: float | None) -> int:
    if investment_cr is not None:
        if investment_cr >= 100:
            return 15
        if investment_cr >= 25:
            return 11
        if investment_cr >= 5:
            return 7
        return 3
    if area_sqft is not None:
        if area_sqft >= 200_000:
            return 14
        if area_sqft >= 50_000:
            return 10
        return 5
    if tender_value_inr is not None:
        cr = tender_value_inr / 1e7
        if cr >= 10:
            return 13
        if cr >= 2:
            return 9
        return 5
    return 4


def score_project(project, company=None, evidence=(), contacts=(), now: datetime | None = None) -> tuple[int, Grade, dict]:
    now = now or datetime.now(timezone.utc)
    b: dict[str, float] = {}

    b["project_type"] = TYPE_POINTS.get(project.project_type, 5)
    b["stage"] = STAGE_POINTS.get(project.stage, 6)

    dates = [_aware(e.published_at) for e in evidence if e.published_at]
    if project.announcement_date:
        dates.append(_aware(project.announcement_date))
    latest = max(dates) if dates else _aware(project.last_evidence_at)
    b["recency"] = _recency_points(latest, now)

    b["location"] = 10 if project.cluster else 3
    b["size"] = _size_points(project.investment_inr_crore, project.area_sqft, project.tender_value_inr)

    if project.kind == OpportunityKind.TENDER:
        b["company"] = 6
    else:
        tier = company.size_tier if company else "unknown"
        b["company"] = SIZE_POINTS.get(tier, 3) + (2 if company and company.is_quality else 0)

    kinds = {e.source_kind for e in evidence}
    b["evidence"] = max((SOURCE_POINTS.get(k, 3) for k in kinds), default=0) + min(4, 2 * (len(evidence) - 1))

    if project.kind == OpportunityKind.TENDER:
        b["contact"] = 5  # tenders are actioned via the portal, not email
    else:
        reachable = [c for c in contacts if c.email and not c.do_not_contact and c.email_status not in ("invalid", "bounced")]
        if any(c.role_category in DECISION_ROLES and not c.is_generic for c in reachable):
            b["contact"] = 8
        elif reachable:
            b["contact"] = 4
        elif contacts:
            b["contact"] = 2
        else:
            b["contact"] = 0

    raw = sum(b.values())
    confidence = max(0.0, min(1.0, project.ai_confidence or 0.0))
    multiplier = 0.55 + 0.45 * confidence
    score = round(min(100, raw) * multiplier)

    # Hard gates: stale or irrelevant opportunities can never rank above LOW.
    if not project.is_relevant or not project.is_current:
        score = min(score, 30)
        b["gate"] = "not current" if project.is_relevant else "not relevant"
    if project.kind == OpportunityKind.TENDER and project.tender_closing_at:
        closing = project.tender_closing_at
        if closing.tzinfo is None:
            closing = closing.replace(tzinfo=timezone.utc)
        if closing < now:
            score = min(score, 20)
            b["gate"] = "tender closed"

    b["confidence_multiplier"] = round(multiplier, 2)
    b["raw_total"] = raw
    return score, grade_for(score), b


def score_company(company, project_scores: list[int]) -> tuple[int, Grade]:
    if project_scores:
        best = max(project_scores)
    else:
        best = {"large": 30, "mid": 20, "small": 8}.get(company.size_tier, 10)
        if company.is_quality:
            best += 10
    return best, grade_for(best)
