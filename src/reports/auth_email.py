"""Send magic-link sign-in emails via SendGrid.

Renders ``src/reports/templates/magic_link_email.html`` and POSTs it to
the SendGrid v3 API. Mirrors the pattern in ``src/reports/email.py`` —
no shared base class, just the raw HTTP call repeated deliberately so
the auth path doesn't drag in the full report rendering pipeline.

When ``settings.sendgrid_api_key`` is empty or the placeholder, the
email body is logged to stdout instead of being sent. This keeps local
development working without a SendGrid account.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import jinja2

from src.config import get_settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

_DEV_PLACEHOLDER_KEYS = {"", "placeholder", "dev-placeholder"}


def _render_magic_link_email(magic_link: str, ttl_minutes: int) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("magic_link_email.html")
    return template.render(magic_link=magic_link, ttl_minutes=ttl_minutes)


async def send_magic_link(email: str, magic_link: str) -> bool:
    """Send a magic-link email to ``email``.

    Returns ``True`` when SendGrid accepted the request (HTTP 200/202)
    or when running in local dev mode (placeholder API key) — in the
    latter case the link is logged to stdout so developers can copy it.
    """
    settings = get_settings()
    html_content = _render_magic_link_email(
        magic_link=magic_link,
        ttl_minutes=settings.auth_magic_link_ttl_minutes,
    )

    # Dev mode: no real SendGrid key — log the link and pretend success
    # so the auth flow still works end-to-end locally.
    if settings.sendgrid_api_key in _DEV_PLACEHOLDER_KEYS:
        logger.info("=" * 72)
        logger.info("DEV MODE: magic-link email would be sent to %s", email)
        logger.info("Magic link: %s", magic_link)
        logger.info("=" * 72)
        return True

    payload: dict[str, object] = {
        "personalizations": [
            {
                "to": [{"email": email}],
                "subject": "Sign in to the Ad Creative Agent dashboard",
            },
        ],
        "from": {"email": settings.report_email_from},
        "content": [
            {"type": "text/html", "value": html_content},
        ],
    }

    headers: dict[str, str] = {
        "Authorization": f"Bearer {settings.sendgrid_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _SENDGRID_API_URL,
                json=payload,
                headers=headers,
            )
            if response.status_code in (200, 202):
                logger.info("Magic-link email sent to %s", email)
                return True

            logger.error(
                "SendGrid returned HTTP %d: %s",
                response.status_code,
                response.text[:500],
            )
            return False
    except httpx.RequestError as exc:
        logger.error("SendGrid request failed: %s", exc)
        return False
