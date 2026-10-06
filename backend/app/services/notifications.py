"""Slack / Telegram / email notifications. Failures are logged, never raised."""

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def notify(title: str, lines: list[str] | None = None, link: str | None = None) -> None:
    body = "\n".join(lines or [])
    if link:
        body += f"\n{link}"
    if settings.slack_webhook_url:
        try:
            httpx.post(settings.slack_webhook_url, json={"text": f"*{title}*\n{body}"}, timeout=10).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Slack notify failed: %s", exc)
    if settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            httpx.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": settings.telegram_chat_id, "text": f"{title}\n{body}", "disable_web_page_preview": True},
                timeout=10,
            ).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Telegram notify failed: %s", exc)
    if settings.notify_email and settings.smtp_host:
        try:
            msg = EmailMessage()
            msg["From"] = settings.sender_email or settings.smtp_user
            msg["To"] = settings.notify_email
            msg["Subject"] = f"[Lead Engine] {title}"
            msg.set_content(body)
            _smtp_send(msg)
        except Exception as exc:  # noqa: BLE001
            log.warning("Email notify failed: %s", exc)
    if not (settings.slack_webhook_url or settings.telegram_bot_token or settings.notify_email):
        log.info("NOTIFY %s | %s", title, body.replace("\n", " | "))


def _smtp_send(msg: EmailMessage) -> None:
    if settings.smtp_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
