"""Idempotent seeding of default monitoring sources. Run: python -m app.seed"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.models import Source, SourceKind

NEWS_QUERIES = [
    '"{c}" factory OR plant OR "manufacturing unit"',
    '"{c}" warehouse OR "logistics park" OR PEB',
    '"{c}" expansion OR investment crore',
    '"{c}" RIICO land allotment OR "industrial area"',
]
SEARCH_QUERIES = [
    '"{c}" new plant construction',
    '"{c}" factory expansion 2026',
    '"{c}" warehouse construction',
]


def default_sources() -> list[dict]:
    out: list[dict] = []
    for c in settings.target_clusters:
        for i, q in enumerate(NEWS_QUERIES, 1):
            query = q.format(c=c)
            out.append(dict(name=f"Google News · {c} #{i}", kind=SourceKind.NEWS_RSS, interval_minutes=180,
                            config={"query": query, "provider": "google"}))
        for i, q in enumerate(SEARCH_QUERIES, 1):
            out.append(dict(name=f"Web search · {c} #{i}", kind=SourceKind.SEARCH, interval_minutes=720,
                            config={"query": q.format(c=c), "recency_days": 60, "num": 10},
                            enabled=settings.search_provider != "none"))
    out += [
        dict(name="RIICO · Home notices & press", kind=SourceKind.LISTING, interval_minutes=360,
             url="https://riico.rajasthan.gov.in/", config={"only_documents": True}),
        dict(name="RIICO · Press releases", kind=SourceKind.LISTING, interval_minutes=720,
             url="https://riico.rajasthan.gov.in/PressRelease.aspx?menu_id=41", config={"only_documents": True}),
        dict(name="RIICO · Public notices", kind=SourceKind.LISTING, interval_minutes=720,
             url="https://riico.rajasthan.gov.in/PublicNotice.aspx?menu_id=73", config={"only_documents": True}),
        dict(name="Rajasthan e-Proc · Latest tenders", kind=SourceKind.TENDER_TABLE, interval_minutes=120,
             url="https://eproc.rajasthan.gov.in/nicgep/app"),
        dict(name="CPPP · Latest active tenders", kind=SourceKind.TENDER_TABLE, interval_minutes=180,
             url="https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata"),
    ]
    return out


def seed_sources(db: Session) -> int:
    added = 0
    for spec in default_sources():
        if db.scalar(select(Source.id).where(Source.name == spec["name"])):
            continue
        db.add(Source(**{"config": {}, "enabled": True, **spec}))
        added += 1
    db.flush()
    return added


if __name__ == "__main__":
    with session_scope() as db:
        print(f"Seeded {seed_sources(db)} sources")
