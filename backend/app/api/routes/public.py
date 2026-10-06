"""Unauthenticated endpoints: health and unsubscribe (incl. RFC 8058 one-click)."""

import html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services.suppression import suppress, verify_unsubscribe_token

router = APIRouter(tags=["public"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:520px;margin:12vh auto;padding:0 16px;color:#1f2937}}
button{{background:#111827;color:#fff;border:0;padding:10px 18px;border-radius:6px;font-size:15px;cursor:pointer}}</style>
</head><body>{body}</body></html>"""
    )


@router.get("/u/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    email = verify_unsubscribe_token(token)
    if not email:
        raise HTTPException(404, "Invalid link")
    company = html.escape(settings.sender_company or "us")
    return _page(
        "Unsubscribe",
        f"<h2>Unsubscribe</h2><p>Stop all emails from {company} to <b>{html.escape(email)}</b>?</p>"
        f'<form method="post"><button type="submit">Unsubscribe</button></form>',
    )


@router.post("/u/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """Handles both the confirmation button and List-Unsubscribe-Post one-click requests."""
    email = verify_unsubscribe_token(token)
    if not email:
        raise HTTPException(404, "Invalid link")
    suppress(db, email=email, reason="unsubscribe", note="unsubscribe link")
    db.commit()
    return _page("Unsubscribed", f"<h2>You're unsubscribed</h2><p>{html.escape(email)} will not receive further emails from us.</p>")
