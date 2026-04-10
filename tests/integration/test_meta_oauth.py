"""Integration tests for the Phase B Meta OAuth endpoints.

Walks every ``/api/me/meta/*`` and ``/api/auth/meta/callback`` path
against a mocked Graph API and a mocked DB session. No real network
I/O, no Postgres. The Graph API calls in
``src.dashboard.meta_oauth`` are patched directly because they're
thin functions rather than a class — cleaner than stubbing httpx.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dashboard_app
from src.dashboard.auth import (
    create_oauth_state_token,
    create_session_token,
)
from src.dashboard.deps import get_db_session
from src.dashboard.meta_oauth import MetaTokenResponse


def _make_user():
    return SimpleNamespace(id=uuid4(), email="alice@example.com", is_active=True)


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(dashboard_app.app)
    yield c
    dashboard_app.app.dependency_overrides.clear()


def _override_session(session) -> None:
    async def _fake():
        yield session

    dashboard_app.app.dependency_overrides[get_db_session] = _fake


def _signed_in_client(client: TestClient, user) -> str:
    """Set session + csrf cookies on the client and return the csrf value."""
    token = create_session_token(user.id)
    csrf = "csrf-value"
    client.cookies.set("session_token", token)
    client.cookies.set("csrf_token", csrf)
    return csrf


# ---------------------------------------------------------------------------
# POST /api/me/meta/connect
# ---------------------------------------------------------------------------


class TestMetaConnect:
    def test_returns_authorize_url(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
        _override_session(session)
        csrf = _signed_in_client(client, user)

        resp = client.post("/api/me/meta/connect", headers={"X-CSRF-Token": csrf})
        client.cookies.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "auth_url" in body
        assert "facebook.com" in body["auth_url"]
        assert "state=" in body["auth_url"]
        assert "scope=ads_management" in body["auth_url"]

    def test_requires_authentication(self, client: TestClient) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))
        _override_session(session)
        # Provide CSRF so we get past the CSRF gate and hit the auth check.
        csrf = "csrf-value"
        client.cookies.set("csrf_token", csrf)
        try:
            resp = client.post("/api/me/meta/connect", headers={"X-CSRF-Token": csrf})
        finally:
            client.cookies.clear()
        assert resp.status_code == 401

    def test_requires_csrf(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
        _override_session(session)
        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            resp = client.post("/api/me/meta/connect")
        finally:
            client.cookies.clear()
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/auth/meta/callback
# ---------------------------------------------------------------------------


class TestMetaCallback:
    def test_declined_by_user_redirects_with_error(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)
        resp = client.get(
            "/api/auth/meta/callback",
            params={"error": "access_denied", "error_description": "user said no"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "meta_error=declined" in resp.headers["location"]

    def test_missing_params_redirects_with_error(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)
        resp = client.get("/api/auth/meta/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert "meta_error=missing_params" in resp.headers["location"]

    def test_invalid_state_redirects_with_error(self, client: TestClient) -> None:
        session = AsyncMock()
        _override_session(session)
        resp = client.get(
            "/api/auth/meta/callback",
            params={"code": "abc", "state": "garbage"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "meta_error=invalid_state" in resp.headers["location"]

    def test_happy_path_upserts_connection_and_redirects_success(self, client: TestClient) -> None:
        user_id = uuid4()
        state = create_oauth_state_token(user_id)

        short = MetaTokenResponse(
            access_token="short-lived-abc",
            token_type="bearer",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        long_lived = MetaTokenResponse(
            access_token="long-lived-xyz",
            token_type="bearer",
            expires_at=datetime.now(UTC) + timedelta(days=60),
        )

        session = AsyncMock()
        _override_session(session)

        # Phase G: the callback now also enumerates ad accounts + Pages
        # off the user's token, so mock those helpers too. A single-account
        # / single-page response exercises the happy path where the
        # callback can auto-pick defaults without prompting.
        from src.models.oauth import MetaAdAccountInfo, MetaPageInfo

        fake_accounts = [
            MetaAdAccountInfo(
                id="act_1234567890",
                name="Operator Main",
                account_status=1,
                currency="USD",
            )
        ]
        fake_pages = [
            MetaPageInfo(
                id="111111111",
                name="Slice Society",
                category="Restaurant",
            )
        ]

        with (
            patch(
                "src.dashboard.app.exchange_code_for_token",
                new=AsyncMock(return_value=short),
            ),
            patch(
                "src.dashboard.app.exchange_short_for_long_lived",
                new=AsyncMock(return_value=long_lived),
            ),
            patch(
                "src.dashboard.app.fetch_meta_user_id",
                new=AsyncMock(return_value="9876543210"),
            ),
            patch(
                "src.dashboard.app.fetch_meta_ad_accounts",
                new=AsyncMock(return_value=fake_accounts),
            ),
            patch(
                "src.dashboard.app.fetch_meta_pages",
                new=AsyncMock(return_value=fake_pages),
            ),
            patch(
                "src.dashboard.app.encrypt_token",
                return_value="ENC(long-lived-xyz)",
            ),
            patch(
                "src.dashboard.app.upsert_meta_connection",
                new=AsyncMock(return_value=SimpleNamespace(user_id=user_id)),
            ) as mock_upsert,
        ):
            resp = client.get(
                "/api/auth/meta/callback",
                params={"code": "oauth-code", "state": state},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        assert "meta_connected=1" in resp.headers["location"]
        mock_upsert.assert_awaited_once()
        kwargs = mock_upsert.await_args.kwargs
        assert kwargs["user_id"] == user_id
        assert kwargs["meta_user_id"] == "9876543210"
        assert kwargs["encrypted_access_token"] == "ENC(long-lived-xyz)"
        assert kwargs["token_expires_at"] == long_lived.expires_at


# ---------------------------------------------------------------------------
# GET /api/me/meta/status
# ---------------------------------------------------------------------------


class TestMetaStatus:
    def test_not_connected_returns_false(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
        _override_session(session)
        _signed_in_client(client, user)

        with patch(
            "src.dashboard.app.get_meta_connection",
            new=AsyncMock(return_value=None),
        ):
            resp = client.get("/api/me/meta/status")
        client.cookies.clear()

        assert resp.status_code == 200
        body = resp.json()
        # Phase G: the status payload always surfaces the enumerated
        # ad accounts + Pages + defaults so the dashboard can render
        # picker state without a second roundtrip. Disconnected users
        # get empty lists + null defaults.
        assert body == {
            "connected": False,
            "meta_user_id": None,
            "connected_at": None,
            "token_expires_at": None,
            "available_ad_accounts": [],
            "available_pages": [],
            "default_ad_account_id": None,
            "default_page_id": None,
        }

    def test_connected_returns_metadata(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
        _override_session(session)
        _signed_in_client(client, user)

        expires = datetime.now(UTC) + timedelta(days=60)
        connected = datetime.now(UTC)
        fake_conn = SimpleNamespace(
            user_id=user.id,
            meta_user_id="9876543210",
            connected_at=connected,
            token_expires_at=expires,
            # Phase G: the connection row now carries the enumerated
            # allowlist and per-tenant defaults.
            available_ad_accounts=[
                {
                    "id": "act_1234567890",
                    "name": "Operator Main",
                    "account_status": 1,
                    "currency": "USD",
                }
            ],
            available_pages=[
                {
                    "id": "111111111",
                    "name": "Slice Society",
                    "category": "Restaurant",
                }
            ],
            default_ad_account_id="act_1234567890",
            default_page_id="111111111",
        )
        with patch(
            "src.dashboard.app.get_meta_connection",
            new=AsyncMock(return_value=fake_conn),
        ):
            resp = client.get("/api/me/meta/status")
        client.cookies.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["meta_user_id"] == "9876543210"
        assert body["connected_at"] is not None
        assert body["token_expires_at"] is not None
        # Phase G: check the new fields flow through the status response.
        assert body["default_ad_account_id"] == "act_1234567890"
        assert body["default_page_id"] == "111111111"
        assert len(body["available_ad_accounts"]) == 1
        assert body["available_ad_accounts"][0]["id"] == "act_1234567890"
        assert len(body["available_pages"]) == 1


# ---------------------------------------------------------------------------
# DELETE /api/me/meta/connection
# ---------------------------------------------------------------------------


class TestMetaDisconnect:
    def test_requires_csrf(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            resp = client.delete("/api/me/meta/connection")
        finally:
            client.cookies.clear()

        assert resp.status_code == 403

    def test_deletes_connection_with_csrf(self, client: TestClient) -> None:
        user = _make_user()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
        _override_session(session)
        csrf = _signed_in_client(client, user)

        with patch(
            "src.dashboard.app.delete_meta_connection",
            new=AsyncMock(return_value=True),
        ) as mock_delete:
            resp = client.delete(
                "/api/me/meta/connection",
                headers={"X-CSRF-Token": csrf},
            )
        client.cookies.clear()

        assert resp.status_code == 204
        mock_delete.assert_awaited_once()
