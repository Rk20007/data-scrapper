import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, companies, dashboard, emails, leads, public
from app.config import settings

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if settings.environment == "production" and (
    settings.secret_key.startswith("change-me") or settings.admin_password == "change-me"
):
    raise RuntimeError("Set SECRET_KEY and ADMIN_PASSWORD before running in production")

app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(emails.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
