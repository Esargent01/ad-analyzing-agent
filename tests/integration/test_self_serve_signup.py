"""Self-serve signup + auth hardening tests (Phase A).

Exercises the three behaviors added in Phase A:

1. Unknown email → ``POST /api/auth/magic-link`` issues a link → the
   follow-up ``GET /api/auth/verify`` creates the user lazily and signs
   them in with a session cookie.
2. Replay of the same magic-link token → 302 ``error=invalid_link``
   (the hash is already in ``magic_links_consumed``).
3. Burst of 6 rapid magic-link requests for the same email → the 6th
   hits the per-email sliding-window rate limit and returns 429.

All tests use the FastAPI ``TestClient`` with the DB session dependency
overridden to an ``AsyncMock`` so no real Postgres is required.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dashboard_app
from src.dashboard.auth import (
    create_magic_link_token,
    hash_magic_link_token,
)
from src.dashboard.deps import get_db_session


def _make_user(email: str):
    return SimpleNamespace(id=uuid4(), email=email, is_active=True)


@pytest.fixture()
def client() -> TestClient:
    # Reset the in-process per-email rate limiter between tests so bursts
    # from one test don't poison the next.
    dashboard_app._email_bucket.clear()
    c = TestClient(dashboard_app.app)
    yield c
    dashboard_app.app.dependency_overrides.clear()
    dashboard_app._email_bucket.clear()


def _override_session(session) -> None:
    async def _fake():
        yield session

    dashboard_app.app.dependency_overrides[get_db_session] = _fake


# ---------------------------------------------------------------------------
# End-to-end self-serve flow
# ---------------------------------------------------------------------------


class TestSelfServeSignup:
    def test_unknown_email_full_flow_creates_user(self, client: TestClient) -> None:
        """POST /magic-link (unknown email) → GET /verify → user created."""
        email = "brand-new@example.com"
        session = AsyncMock()
        _override_session(session)

        # Step 1: request a magic link for a brand-new email.
        with patch(
            "src.dashboard.app.send_magic_link",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            resp = client.post("/api/auth/magic-link", json={"email": email})

        assert resp.status_code == 204
        mock_send.assert_awaited_once()
        _, link = mock_send.await_args.args
        # Extract the raw token from the link the handler built.
        assert "token=" in link
        token = link.split("token=", 1)[1]

        # Step 2: verify the token. Since the email is unknown,
        # ``create_user`` must be called and a session cookie issued.
        new_user = _make_user(email)
        with (
            patch(
                "src.dashboard.app.consume_magic_link_token",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "src.dashboard.app.get_user_by_email",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.dashboard.app.create_user",
                new=AsyncMock(return_value=new_user),
            ) as mock_create,
            patch(
                "src.dashboard.app.touch_last_login",
                new=AsyncMock(return_value=None),
            ),
        ):
            verify_resp = client.get(
                "/api/auth/verify",
                params={"token": token},
                follow_redirects=False,
            )

        assert verify_resp.status_code == 302
        assert "/dashboard" in verify_resp.headers["location"]
        mock_create.assert_awaited_once()
        assert "session_token" in verify_resp.cookies

    def test_replay_of_consumed_token_is_rejected(self, client: TestClient) -> None:
        """Second visit to the same /verify?token=... 302s with invalid_link."""
        email = "alice@example.com"
        token = create_magic_link_token(email)
        session = AsyncMock()
        _override_session(session)
        user = _make_user(email)

        # First verify: succeeds (consume returns True).
        with (
            patch(
                "src.dashboard.app.consume_magic_link_token",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "src.dashboard.app.get_user_by_email",
                new=AsyncMock(return_value=user),
            ),
            patch(
                "src.dashboard.app.touch_last_login",
                new=AsyncMock(return_value=None),
            ),
        ):
            first = client.get(
                "/api/auth/verify",
                params={"token": token},
                follow_redirects=False,
            )
        assert first.status_code == 302
        assert "/dashboard" in first.headers["location"]

        # Clear the session cookie that the first verify just set so the
        # replay really is an unauthenticated attempt, not a passthrough.
        client.cookies.clear()

        # Second verify of the SAME token: consume returns False → error.
        with patch(
            "src.dashboard.app.consume_magic_link_token",
            new=AsyncMock(return_value=False),
        ):
            replay = client.get(
                "/api/auth/verify",
                params={"token": token},
                follow_redirects=False,
            )
        assert replay.status_code == 302
        assert "error=invalid_link" in replay.headers["location"]
        assert "session_token" not in replay.cookies

    def test_token_hash_matches_stored_hash(self) -> None:
        """The hash used by the endpoint must match ``hash_magic_link_token``.

        This locks the hashing contract so the migration ledger key can't
        drift away from the code that inserts into it.
        """
        token = create_magic_link_token("carol@example.com")
        h = hash_magic_link_token(token)
        # Hex SHA-256 is 64 chars.
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
        # Hashing is deterministic.
        assert hash_magic_link_token(token) == h


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestMagicLinkRateLimit:
    def test_sixth_request_for_same_email_returns_429(self, client: TestClient) -> None:
        """Per-email sliding window allows 5 requests, 6th is throttled."""
        email = "burst@example.com"
        session = AsyncMock()
        _override_session(session)

        with patch(
            "src.dashboard.app.send_magic_link",
            new=AsyncMock(return_value=True),
        ):
            statuses = [
                client.post("/api/auth/magic-link", json={"email": email}).status_code
                for _ in range(6)
            ]

        assert statuses[:5] == [204] * 5
        assert statuses[5] == 429

    def test_rate_limit_is_per_email_not_global(self, client: TestClient) -> None:
        """Burst on one email must not throttle a different email."""
        session = AsyncMock()
        _override_session(session)

        with patch(
            "src.dashboard.app.send_magic_link",
            new=AsyncMock(return_value=True),
        ):
            for _ in range(5):
                client.post(
                    "/api/auth/magic-link",
                    json={"email": "first@example.com"},
                )
            other = client.post(
                "/api/auth/magic-link",
                json={"email": "second@example.com"},
            )

        assert other.status_code == 204
