"""Settings that operators can change from the dashboard without a redeploy."""

from dataclasses import dataclass, fields

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Grade

SEND_MODES = ("dry_run", "approval", "auto")


@dataclass
class RuntimeSettings:
    email_send_mode: str
    outreach_min_grade: str
    auto_send_min_grade: str
    daily_send_limit: int
    hourly_send_limit: int
    per_domain_daily_limit: int
    min_seconds_between_sends: int
    send_window_start_hour: int
    send_window_end_hour: int
    send_on_weekends: bool
    followup_delays_days: list[int]
    max_followups: int
    company_cooldown_days: int
    notify_min_grade: str


RUNTIME_KEYS = [f.name for f in fields(RuntimeSettings)]


def _validate(key: str, value):
    if key == "email_send_mode":
        if value not in SEND_MODES:
            raise ValueError(f"email_send_mode must be one of {SEND_MODES}")
    elif key.endswith("_grade"):
        if value not in Grade.__members__:
            raise ValueError(f"{key} must be one of {list(Grade.__members__)}")
    elif key == "send_on_weekends":
        if not isinstance(value, bool):
            raise ValueError("send_on_weekends must be boolean")
    elif key == "followup_delays_days":
        if not isinstance(value, list) or not all(isinstance(v, int) and v > 0 for v in value):
            raise ValueError("followup_delays_days must be a list of positive integers")
    else:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        if key.startswith("send_window") and value > 24:
            raise ValueError(f"{key} must be between 0 and 24")
    return value


def get_runtime(db: Session) -> RuntimeSettings:
    values = {k: getattr(settings, k) for k in RUNTIME_KEYS}
    for row in db.query(AppSetting).filter(AppSetting.key.in_(RUNTIME_KEYS)):
        values[row.key] = row.value
    return RuntimeSettings(**values)


def update_runtime(db: Session, data: dict) -> RuntimeSettings:
    for key, value in data.items():
        if key not in RUNTIME_KEYS:
            raise ValueError(f"Unknown setting: {key}")
        _validate(key, value)
    for key, value in data.items():
        row = db.get(AppSetting, key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.flush()
    rt = get_runtime(db)
    if rt.send_window_start_hour >= rt.send_window_end_hour:
        raise ValueError("send_window_start_hour must be before send_window_end_hour")
    return rt
