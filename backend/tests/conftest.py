import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["OPENAI_API_KEY"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "pw"
os.environ["SENDER_EMAIL"] = "sales@contractor.example.in"
os.environ["SENDER_COMPANY"] = "Acme Infra"
os.environ["SENDER_ADDRESS"] = "Plot 1, Bhiwadi, Rajasthan"
os.environ["SMTP_HOST"] = "smtp.test.local"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # unreachable on purpose: code must degrade gracefully

import pytest  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _schema(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    import app.services.contacts as contacts

    monkeypatch.setattr(contacts, "_mx_ok", lambda domain: True)  # no DNS in tests
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
