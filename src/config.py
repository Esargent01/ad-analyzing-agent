"""Application configuration via pydantic-settings."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Pre-load .env so that empty environment variables (e.g. ANTHROPIC_API_KEY="")
# set by parent processes don't shadow the .env values. pydantic-settings treats
# an empty env var as "set" and skips the .env file for that key.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for key, value in dotenv_values(_ENV_FILE).items():
        if value and not os.environ.get(key):
            os.environ[key] = value


class Settings(BaseSettings):
    """All application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://adagent:adagent_dev@localhost:5432/adagent"

    # Anthropic
    anthropic_api_key: str = "sk-ant-placeholder"
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Meta Marketing API
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_page_id: str = ""
    meta_landing_page_url: str = "https://example.com"

    # Google Ads
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_customer_id: str = ""

    # Slack
    slack_webhook_url: str = ""

    # Email (SendGrid)
    sendgrid_api_key: str = ""
    report_email_to: str = "team@company.com"
    report_email_from: str = "adagent@company.com"

    # Report hosting
    report_output_dir: str = "./public"
    report_base_url: str = "https://esargent01.github.io/ad-analyzing-agent"

    # Application
    log_level: str = "INFO"
    cycle_schedule_cron: str = "0 6 * * *"
    max_concurrent_variants: int = 10
    min_impressions: int = Field(default=1000)
    confidence_threshold: float = Field(default=0.95)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


# Module-level convenience alias used throughout the codebase:
#   from src.config import settings
settings: Settings = get_settings()
