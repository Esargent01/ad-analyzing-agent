"""HMAC-signed review tokens for the weekly approval flow.

Tokens are opaque URL-safe strings that embed a campaign UUID and an
expiration timestamp. They're used to grant no-login access to the
weekly review page linked from the email report.

Format (before encoding):
    <campaign_id>:<expires_at_unix>:<signature>

Signature is HMAC-SHA256 of "<campaign_id>:<expires_at_unix>" using the
REVIEW_TOKEN_SECRET from settings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.config import get_settings

logger = logging.getLogger(__name__)


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_review_token(campaign_id: UUID, ttl_days: int | None = None) -> str:
    """Create a signed review token for the given campaign.

    The token embeds the campaign UUID and an expiry timestamp; it can
    be verified without any database lookup.
    """
    settings = get_settings()
    ttl = ttl_days if ttl_days is not None else settings.review_token_ttl_days
    expires_at = int((datetime.now(UTC) + timedelta(days=ttl)).timestamp())
    payload = f"{campaign_id}:{expires_at}"
    signature = _sign(payload, settings.review_token_secret)
    raw = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def verify_review_token(token: str) -> UUID | None:
    """Verify a review token. Returns the campaign UUID if valid, else None.

    Returns None on:
    - malformed tokens
    - invalid signatures
    - expired tokens
    """
    settings = get_settings()
    try:
        # Re-pad base64 if needed
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding).decode("utf-8")
        campaign_str, expires_str, signature = raw.rsplit(":", 2)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.debug("Malformed review token: %s", exc)
        return None

    payload = f"{campaign_str}:{expires_str}"
    expected = _sign(payload, settings.review_token_secret)
    if not hmac.compare_digest(expected, signature):
        logger.debug("Invalid review token signature")
        return None

    try:
        expires_at = int(expires_str)
    except ValueError:
        logger.debug("Invalid review token expiry")
        return None

    if datetime.now(UTC).timestamp() > expires_at:
        logger.debug("Expired review token")
        return None

    try:
        return UUID(campaign_str)
    except ValueError:
        logger.debug("Invalid review token campaign UUID")
        return None
