"""HMAC-signed tokens for dashboard auth.

Two token flavors:

1. **Magic-link tokens** — short-lived (15 min), embed the target email
   address, delivered via email. Verifying one proves the holder controls
   the email.

2. **Session tokens** — longer-lived (30 days), embed the authenticated
   user's UUID, stored as an HttpOnly cookie. Presented on every
   subsequent request.

Both use HMAC-SHA256 over ``<payload>:<expires_at_unix>`` signed with
``settings.auth_session_secret``. The helpers are modelled on the existing
``src/dashboard/tokens.py`` HMAC pattern so the two stay consistent.

A third helper generates CSRF tokens — opaque URL-safe random strings
used as a double-submit defense on state-changing requests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.config import get_settings

logger = logging.getLogger(__name__)

# Distinct prefixes prevent a magic-link token from being reused as a
# session token (or vice versa) — the HMAC covers the prefix, so flipping
# it invalidates the signature.
_MAGIC_LINK_PREFIX = "ml"
_SESSION_PREFIX = "sn"


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _encode(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode(token: str) -> str:
    padding = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + padding).decode("utf-8")


# ---------------------------------------------------------------------------
# Magic-link tokens (email -> one-time sign-in link)
# ---------------------------------------------------------------------------


def create_magic_link_token(email: str, ttl_minutes: int | None = None) -> str:
    """Create a signed magic-link token for the given email address.

    The token embeds the email and an expiry timestamp; it can be
    verified without any database lookup.
    """
    settings = get_settings()
    ttl = ttl_minutes if ttl_minutes is not None else settings.auth_magic_link_ttl_minutes
    expires_at = int((datetime.now(timezone.utc) + timedelta(minutes=ttl)).timestamp())

    payload = f"{_MAGIC_LINK_PREFIX}:{email}:{expires_at}"
    signature = _sign(payload, settings.auth_session_secret)
    return _encode(f"{payload}:{signature}")


def verify_magic_link_token(token: str) -> str | None:
    """Verify a magic-link token. Returns the embedded email on success.

    Returns ``None`` if the token is malformed, signed with the wrong
    secret, has expired, or isn't a magic-link token (wrong prefix).
    """
    settings = get_settings()
    try:
        raw = _decode(token)
        prefix, email, expires_str, signature = raw.rsplit(":", 3)
        # Prefix is the first segment — after stripping the trailing 3, it
        # should equal ``ml``. Use rsplit so emails containing ':' don't break.
        if prefix != _MAGIC_LINK_PREFIX:
            logger.debug("Token prefix is not a magic-link prefix")
            return None
    except (ValueError, UnicodeDecodeError) as exc:
        logger.debug("Malformed magic-link token: %s", exc)
        return None

    payload = f"{prefix}:{email}:{expires_str}"
    expected = _sign(payload, settings.auth_session_secret)
    if not hmac.compare_digest(expected, signature):
        logger.debug("Invalid magic-link token signature")
        return None

    try:
        expires_at = int(expires_str)
    except ValueError:
        logger.debug("Invalid magic-link token expiry")
        return None

    if datetime.now(timezone.utc).timestamp() > expires_at:
        logger.debug("Expired magic-link token")
        return None

    return email


# ---------------------------------------------------------------------------
# Session tokens (cookie-backed, long-lived)
# ---------------------------------------------------------------------------


def create_session_token(user_id: UUID, ttl_days: int | None = None) -> str:
    """Create a signed session token for the given user.

    Stored as the ``session_token`` HttpOnly cookie. Verified on every
    request that passes through :func:`get_current_user` in ``deps.py``.
    """
    settings = get_settings()
    ttl = ttl_days if ttl_days is not None else settings.auth_session_ttl_days
    expires_at = int((datetime.now(timezone.utc) + timedelta(days=ttl)).timestamp())

    payload = f"{_SESSION_PREFIX}:{user_id}:{expires_at}"
    signature = _sign(payload, settings.auth_session_secret)
    return _encode(f"{payload}:{signature}")


def verify_session_token(token: str) -> UUID | None:
    """Verify a session token. Returns the user UUID on success.

    Returns ``None`` on malformed, expired, tampered, or wrong-prefix
    tokens. Callers should map ``None`` → 401 Unauthorized.
    """
    settings = get_settings()
    try:
        raw = _decode(token)
        prefix, user_str, expires_str, signature = raw.rsplit(":", 3)
        if prefix != _SESSION_PREFIX:
            logger.debug("Token prefix is not a session prefix")
            return None
    except (ValueError, UnicodeDecodeError) as exc:
        logger.debug("Malformed session token: %s", exc)
        return None

    payload = f"{prefix}:{user_str}:{expires_str}"
    expected = _sign(payload, settings.auth_session_secret)
    if not hmac.compare_digest(expected, signature):
        logger.debug("Invalid session token signature")
        return None

    try:
        expires_at = int(expires_str)
    except ValueError:
        logger.debug("Invalid session token expiry")
        return None

    if datetime.now(timezone.utc).timestamp() > expires_at:
        logger.debug("Expired session token")
        return None

    try:
        return UUID(user_str)
    except ValueError:
        logger.debug("Invalid session token user UUID")
        return None


# ---------------------------------------------------------------------------
# CSRF tokens (double-submit cookie pattern)
# ---------------------------------------------------------------------------


def generate_csrf_token() -> str:
    """Return a cryptographically random URL-safe CSRF token.

    Emitted as a *non-HttpOnly* cookie so JS can read it, then echoed
    back in the ``X-CSRF-Token`` header on state-changing requests.
    Because attackers cannot read the cookie cross-origin, matching
    header + cookie proves the request originated from our frontend.
    """
    return secrets.token_urlsafe(32)
