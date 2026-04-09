"""End-to-end auth flow tests for the Phase 2 dashboard API.

These tests drive the ``/api/auth/*`` and ``/api/me`` endpoints through
the FastAPI ``TestClient`` with a fully mocked DB session (no Postgres).
We override the :func:`src.dashboard.deps.get_db_session` dependency
with an AsyncMock and wire its ``.execute()`` results by hand.

We also patch the magic-link email sender so no real HTTP call is made.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dashboard_app
from src.dashboard.auth import create_magic_link_token, create_session_token
from src.dashboard.deps import get_db_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(email: str = "alice@example.com"):
    return SimpleNamespace(
        id=uuid4(),
        email=email,
        is_active=True,
    )


def _make_campaign(name: str = "Spring Sale"):
    return SimpleNamespace(id=uuid4(), name=name, is_active=True)


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(dashboard_app.app)
    yield c
    # Clear dependency overrides between tests.
    dashboard_app.app.dependency_overrides.clear()


def _override_session(session) -> None:
    """Install an async-generator override for ``get_db_session``."""

    async def _fake_get_db_session():
        yield session

    dashboard_app.app.dependency_overrides[get_db_session] = _fake_get_db_session


# ---------------------------------------------------------------------------
# POST /api/auth/magic-link
# ---------------------------------------------------------------------------


class TestMagicLinkRequest:
    def test_unknown_email_still_returns_204(self, client: TestClient) -> None:
        """No enumeration: missing user and known user both 204."""
        session = AsyncMock()
        with patch(
            "src.dashboard.app.get_user_by_email",
            new=AsyncMock(return_value=None),
        ) as mock_lookup, patch(
            "src.dashboard.app.send_magic_link",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            _override_session(session)
            response = client.post(
                "/api/auth/magic-link",
                json={"email": "ghost@example.com"},
            )

        assert response.status_code == 204
        mock_lookup.assert_awaited_once()
        # No email should be sent when the user doesn't exist.
        mock_send.assert_not_awaited()

    def test_known_email_triggers_send(self, client: TestClient) -> None:
        user = _make_user("alice@example.com")
        session = AsyncMock()

        with patch(
            "src.dashboard.app.get_user_by_email",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.dashboard.app.send_magic_link",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            _override_session(session)
            response = client.post(
                "/api/auth/magic-link",
                json={"email": "alice@example.com"},
            )

        assert response.status_code == 204
        mock_send.assert_awaited_once()
        # The link URL must contain a valid magic-link token.
        args, _ = mock_send.await_args
        email_arg, link_arg = args
        assert email_arg == "alice@example.com"
        assert "token=" in link_arg

    def test_invalid_email_returns_422(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)
        response = client.post("/api/auth/magic-link", json={"email": "not-an-email"})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/auth/verify
# ---------------------------------------------------------------------------


class TestVerifyEndpoint:
    def test_invalid_token_redirects_with_error(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)

        response = client.get(
            "/api/auth/verify",
            params={"token": "garbage"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error=invalid_link" in response.headers["location"]

    def test_valid_token_sets_cookies_and_redirects(
        self, client: TestClient
    ) -> None:
        user = _make_user("bob@example.com")
        session = AsyncMock()
        token = create_magic_link_token("bob@example.com")

        with patch(
            "src.dashboard.app.get_user_by_email",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.dashboard.app.touch_last_login",
            new=AsyncMock(return_value=None),
        ):
            _override_session(session)
            response = client.get(
                "/api/auth/verify",
                params={"token": token},
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert "/dashboard" in response.headers["location"]

        cookies = response.cookies
        assert "session_token" in cookies
        assert "csrf_token" in cookies

    def test_token_for_unknown_email_redirects_with_error(
        self, client: TestClient
    ) -> None:
        session = AsyncMock()
        token = create_magic_link_token("nobody@example.com")

        with patch(
            "src.dashboard.app.get_user_by_email",
            new=AsyncMock(return_value=None),
        ):
            _override_session(session)
            response = client.get(
                "/api/auth/verify",
                params={"token": token},
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert "error=invalid_link" in response.headers["location"]


# ---------------------------------------------------------------------------
# GET /api/me
# ---------------------------------------------------------------------------


class TestMeEndpoint:
    def test_missing_session_cookie_returns_401(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)
        response = client.get("/api/me")
        assert response.status_code == 401

    def test_invalid_session_cookie_returns_401(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)
        client.cookies.set("session_token", "garbage")
        try:
            response = client.get("/api/me")
        finally:
            client.cookies.clear()
        assert response.status_code == 401

    def test_valid_session_returns_user_and_campaigns(
        self, client: TestClient
    ) -> None:
        user = _make_user("carol@example.com")
        campaigns = [_make_campaign("Spring Sale"), _make_campaign("Summer")]

        # Mock the user lookup inside get_current_user
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: user)
        )

        token = create_session_token(user.id)

        with patch(
            "src.dashboard.app.get_user_campaigns",
            new=AsyncMock(return_value=campaigns),
        ):
            _override_session(session)
            client.cookies.set("session_token", token)
            try:
                response = client.get("/api/me")
            finally:
                client.cookies.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == user.email
        assert len(body["campaigns"]) == 2
        assert {c["name"] for c in body["campaigns"]} == {"Spring Sale", "Summer"}


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


class TestLogoutEndpoint:
    def test_missing_csrf_returns_403(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: user)
        )
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            response = client.post("/api/auth/logout")
        finally:
            client.cookies.clear()

        assert response.status_code == 403

    def test_mismatched_csrf_returns_403(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: user)
        )
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        client.cookies.set("csrf_token", "aaa")
        try:
            response = client.post(
                "/api/auth/logout", headers={"X-CSRF-Token": "bbb"}
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 403

    def test_matching_csrf_returns_204_and_clears_cookies(
        self, client: TestClient
    ) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: user)
        )
        _override_session(session)

        token = create_session_token(user.id)
        csrf = "matching-csrf-token-value"
        client.cookies.set("session_token", token)
        client.cookies.set("csrf_token", csrf)
        try:
            response = client.post(
                "/api/auth/logout", headers={"X-CSRF-Token": csrf}
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 204
        # The response should set cookies to empty / past expiry to clear them.
        set_cookie = response.headers.get("set-cookie", "")
        assert "session_token" in set_cookie
        assert "csrf_token" in set_cookie
