from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Static configuration loaded from environment / .env.

    Values marked "runtime" can also be overridden from the dashboard
    (stored in the app_settings table, see services/runtime_settings.py).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bhiwadi Lead Engine"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://leads:leads@localhost:5432/leads"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = "change-me-to-a-long-random-string"
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me"
    jwt_expire_hours: int = 24
    cors_origins: list[str] = ["http://localhost:3000"]
    public_base_url: str = "http://localhost:8000"  # used for unsubscribe links
    dashboard_url: str = "http://localhost:3000"  # used in notifications

    # Geography
    target_clusters: list[str] = ["Bhiwadi", "Khushkhera", "Tapukara", "Neemrana"]

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_max_input_chars: int = 14000

    # Web search provider: serpapi | google_cse | none
    search_provider: str = "none"
    serpapi_key: str = ""
    google_cse_key: str = ""
    google_cse_cx: str = ""

    # Crawler etiquette
    crawler_user_agent: str = "LeadEngineBot/1.0 (business research; contact: admin@example.com)"
    crawler_delay_seconds: float = 3.0
    crawler_timeout_seconds: float = 20.0
    crawler_respect_robots: bool = True
    crawler_max_pages_per_site: int = 8

    # Sender identity (used in emails — only verifiable facts!)
    sender_name: str = ""
    sender_title: str = ""
    sender_email: str = ""
    sender_company: str = ""
    sender_phone: str = ""
    sender_website: str = ""
    sender_address: str = ""  # physical postal address shown in footer
    sender_offering: str = "PEB structures, industrial civil construction, factory and warehouse buildings, turnkey EPC"
    sender_credentials: str = ""  # optional verified claims, e.g. "Delivered 40+ industrial sheds in Bhiwadi since 2012"
    reply_to: str = ""
    unsubscribe_mailto: str = ""

    # SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    # IMAP (reply detection)
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # Email automation (runtime)
    email_send_mode: str = "dry_run"  # dry_run | approval | auto
    outreach_min_grade: str = "HIGH"
    auto_send_min_grade: str = "HOT"
    daily_send_limit: int = 30
    hourly_send_limit: int = 8
    per_domain_daily_limit: int = 1
    min_seconds_between_sends: int = 120
    send_window_start_hour: int = 10
    send_window_end_hour: int = 18
    send_on_weekends: bool = False
    timezone: str = "Asia/Kolkata"
    followup_delays_days: list[int] = [4, 7]
    max_followups: int = 2
    company_cooldown_days: int = 45

    # Notifications (runtime: notify_min_grade)
    notify_min_grade: str = "HIGH"
    slack_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_email: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
