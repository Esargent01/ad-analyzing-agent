"""Unit tests for the OAuth state-nonce helpers in ``src.dashboard.auth``.

The state nonce binds a ``POST /api/me/meta/connect`` request to the
eventual ``GET /api/auth/meta/callback``. Attackers intercepting the
callback should not be able to forge a nonce and attach a stolen code
to a different app user.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from src.dashboard.auth import (
    create_oauth_state_token,
    verify_oauth_state_token,
)


class TestOAuthStateRoundTrip:
    def test_round_trip_returns_user_uuid(self) -> None:
        user_id = uuid4()
        token = create_oauth_state_token(user_id)
        assert verify_oauth_state_token(token) == user_id

    def test_garbage_token_returns_none(self) -> None:
        assert verify_oauth_state_token("garbage") is None

    def test_tampered_token_returns_none(self) -> None:
        user_id = uuid4()
        token = create_oauth_state_token(user_id)
        # Flip a char near the middle so the payload but not the
        # signature still parses — defeats the HMAC check.
        mid = len(token) // 2
        tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]
        assert verify_oauth_state_token(tampered) is None

    def test_magic_link_token_is_not_accepted_as_state(self) -> None:
        """The two token flavours must not be interchangeable."""
        from src.dashboard.auth import create_magic_link_token

        magic = create_magic_link_token("alice@example.com")
        # Magic-link tokens carry the ``ml:`` prefix, state tokens carry
        # ``os:`` — verify should reject the wrong prefix.
        assert verify_oauth_state_token(magic) is None

    def test_expired_state_returns_none(self) -> None:
        user_id = uuid4()
        token = create_oauth_state_token(user_id, ttl_minutes=10)

        # Fast-forward time 11 minutes via patching datetime.now
        future = datetime.now(UTC) + timedelta(minutes=11)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future

        with patch("src.dashboard.auth.datetime", _FakeDT):
            assert verify_oauth_state_token(token) is None
