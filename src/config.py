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
        # Silently ignore stray env vars — this makes it safe to
        # leave retired keys (e.g., the pre-Phase-F
        # ``META_ACCESS_TOKEN``) in ``.env`` for backup purposes
        # without crashing the process at startup.
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://adagent:adagent_dev@localhost:5432/adagent"

    # Anthropic
    anthropic_api_key: str = "sk-ant-placeholder"
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Meta Marketing API
    #
    # After Phase F every campaign runs on its *owner's* OAuth token,
    # which is stored encrypted in ``user_meta_connections`` and
    # decrypted on demand by ``src.adapters.meta_factory``. There is
    # no longer a ``META_ACCESS_TOKEN`` environment variable; a user
    # must click "Connect Meta" in the dashboard before their
    # campaigns can run.
    #
    # After Phase G, the ad account / Page / landing-page URL are
    # also per-campaign — enumerated at OAuth callback time into
    # ``user_meta_connections.available_ad_accounts`` / ``_pages``
    # and pinned per-import onto ``campaigns.meta_ad_account_id`` /
    # ``meta_page_id`` / ``landing_page_url``. The old global
    # settings (``META_AD_ACCOUNT_ID``, ``META_PAGE_ID``,
    # ``META_LANDING_PAGE_URL``) are gone.
    #
    # ``meta_app_id`` / ``meta_app_secret`` are still required — they
    # identify the Meta App used for the OAuth exchange itself.
    meta_app_id: str = ""
    meta_app_secret: str = ""

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

    # Weekly review flow
    review_token_secret: str = "dev-secret-change-me-in-production"
    review_token_ttl_days: int = 7
    proposal_ttl_days: int = 14

    # Dashboard auth (Phase 2)
    # NOTE: rotate auth_session_secret in production; signing key for both
    # magic-link tokens and session cookies.
    auth_session_secret: str = "dev-auth-secret-change-me-in-production"
    auth_magic_link_ttl_minutes: int = 15
    auth_session_ttl_days: int = 30

    # Frontend / CORS
    # Comma-separated list of allowed origins (e.g.
    # "http://localhost:5173,https://app.example.com").
    frontend_origins: str = ""
    # Public URL of the frontend — used for post-verify redirects to
    # ``/dashboard`` and ``/sign-in?error=...``.
    frontend_base_url: str = "http://localhost:5173"
    # Public URL of the backend — used to build the magic-link target
    # (``{api_base_url}/api/auth/verify?token=...``). The backend needs
    # its own external URL because the verify endpoint must be reached
    # before any frontend JavaScript runs (the link lives in an email).
    api_base_url: str = "http://localhost:8000"

    # Cookie scoping. Leave ``cookie_domain`` empty on ``*.vercel.app`` /
    # ``*.fly.dev`` — public suffixes reject ``Domain=`` cookies. On a custom
    # domain set e.g. ``.example.com``.
    cookie_domain: str = ""
    cookie_secure: bool = True

    # Meta OAuth (Phase B). The redirect URI must also be added to the
    # Meta App dashboard for both dev (localhost) and production URLs.
    meta_oauth_redirect_uri: str = "http://localhost:8000/api/auth/meta/callback"
    meta_oauth_scopes: str = "ads_management,ads_read,business_management,pages_show_list"
    meta_graph_api_version: str = "v18.0"
    # Fernet key for encrypting stored Meta access tokens at rest.
    # Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # LOSING THIS KEY ORPHANS EVERY STORED META TOKEN — back it up.
    meta_token_encryption_key: str = ""

    # Per-user limits (Phase D+). Tunable once Phase E exposes cost data.
    max_campaigns_per_user: int = 5

    # Twitter / X — OAuth 1.0a User Context (required for POST /2/tweets).
    # Field names match what the X Developer Console calls them (API Key /
    # API Key Secret) and what this project used pre-commit 48e6c6f, so any
    # previously-generated credentials drop straight in. When any of the
    # four is empty or a placeholder, ``src.reports.twitter.post_tweet``
    # logs the draft and skips the real API call so local dev still works.
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


# Module-level convenience alias used throughout the codebase:
#   from src.config import settings
settings: Settings = get_settings()
