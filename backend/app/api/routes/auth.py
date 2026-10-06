from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import check_credentials, create_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginIn):
    if not check_credentials(body.email, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return {"access_token": create_token(body.email.lower()), "token_type": "bearer"}
