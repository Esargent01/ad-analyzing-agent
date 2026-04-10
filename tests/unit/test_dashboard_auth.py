"""Unit tests for HMAC auth tokens in ``src/dashboard/auth.py``.

Covers:
- Round-trip sign/verify for magic-link and session tokens
- Tamper detection (bit flip → invalid)
- Expiry enforcement (with a frozen clock)
- Cross-prefix rejection (a session token should not verify as a
  magic-link token, and vice versa — they share the same HMAC secret).
- CSRF token generation (random, long enough, URL-safe)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from src.dashboard.auth import (
    create_magic_link_token,
    create_session_token,
    generate_csrf_token,
    verify_magic_link_token,
    verify_session_token,
)

# ---------------------------------------------------------------------------
# Magic-link tokens
# ---------------------------------------------------------------------------


class TestMagicLinkTokens:
    def test_sign_verify_round_trip(self):
        email = "alice@example.com"
        token = create_magic_link_token(email)
        assert verify_magic_link_token(token) == email

    def test_email_is_case_preserved(self):
        email = "Mixed.Case@Example.COM"
        token = create_magic_link_token(email)
        # The helper doesn't lowercase — callers (/api/auth/magic-link)
        # normalize before creating the token, so the round-trip is exact.
        assert verify_magic_link_token(token) == email

    def test_garbage_returns_none(self):
        assert verify_magic_link_token("not-a-real-token") is None

    def test_empty_string_returns_none(self):
        assert verify_magic_link_token("") is None

    def test_tampered_signature_returns_none(self):
        token = create_magic_link_token("a@b.com")
        # Flip the last char so the signature check fails.
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert verify_magic_link_token(tampered) is None

    def test_expired_token_returns_none(self):
        token = create_magic_link_token("a@b.com", ttl_minutes=1)
        future = datetime.now(UTC) + timedelta(minutes=5)

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future if tz is None else future.astimezone(tz)

        with patch("src.dashboard.auth.datetime", _FakeDatetime):
            assert verify_magic_link_token(token) is None

    def test_session_token_cannot_verify_as_magic_link(self):
        """The prefix binds the token type; swapping them fails verification."""
        session = create_session_token(uuid4())
        assert verify_magic_link_token(session) is None


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------


class TestSessionTokens:
    def test_sign_verify_round_trip(self):
        user_id = uuid4()
        token = create_session_token(user_id)
        assert verify_session_token(token) == user_id

    def test_garbage_returns_none(self):
        assert verify_session_token("garbage") is None

    def test_empty_string_returns_none(self):
        assert verify_session_token("") is None

    def test_tampered_signature_returns_none(self):
        token = create_session_token(uuid4())
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert verify_session_token(tampered) is None

    def test_expired_token_returns_none(self):
        token = create_session_token(uuid4(), ttl_days=1)
        future = datetime.now(UTC) + timedelta(days=2)

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future if tz is None else future.astimezone(tz)

        with patch("src.dashboard.auth.datetime", _FakeDatetime):
            assert verify_session_token(token) is None

    def test_magic_link_cannot_verify_as_session(self):
        magic = create_magic_link_token("a@b.com")
        assert verify_session_token(magic) is None

    def test_different_users_produce_different_tokens(self):
        a = create_session_token(uuid4())
        b = create_session_token(uuid4())
        assert a != b


# ---------------------------------------------------------------------------
# CSRF tokens
# ---------------------------------------------------------------------------


class TestCsrfTokens:
    def test_tokens_are_unique(self):
        # 1 in 2^256 collision — effectively impossible in a test suite.
        assert generate_csrf_token() != generate_csrf_token()

    def test_tokens_are_url_safe(self):
        t = generate_csrf_token()
        # token_urlsafe characters are [A-Za-z0-9_-]
        assert all(c.isalnum() or c in ("-", "_") for c in t)

    def test_tokens_have_reasonable_length(self):
        # token_urlsafe(32) yields ~43 chars of base64
        t = generate_csrf_token()
        assert len(t) >= 40
