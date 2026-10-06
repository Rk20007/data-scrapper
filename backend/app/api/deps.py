import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


def check_credentials(email: str, password: str) -> bool:
    ok_email = hmac.compare_digest(email.strip().lower(), settings.admin_email.lower())
    ok_pass = hmac.compare_digest(password, settings.admin_password)
    return ok_email and ok_pass


def create_token(subject: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    return jwt.encode({"sub": subject, "exp": exp}, settings.secret_key, algorithm="HS256")


def require_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from None
    return payload["sub"]
