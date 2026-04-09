"""Tests proving cross-user campaign isolation.

``require_campaign_access`` is the single gate between authenticated
users and campaign data. We verify that:

- A request without a session cookie → 401
- A request from user A for a campaign only user B has → 404 (not 403,
  so we never leak that the campaign exists)
- A request from a user who *does* have access flows through

The DB is fully mocked with AsyncMock; we're exercising the dependency
wiring, not real queries.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dashboard_app
from src.dashboard.auth import create_session_token, generate_csrf_token
from src.dashboard.deps import get_db_session


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(dashboard_app.app)
    yield c
    dashboard_app.app.dependency_overrides.clear()


def _make_user(email: str = "alice@example.com"):
    return SimpleNamespace(id=uuid4(), email=email, is_active=True)


def _authed_session_with_membership(user, has_access: bool) -> AsyncMock:
    """Return a session whose ``.execute()`` first yields the user and
    then yields membership (row or None) for the campaign-access check.
    """
    responses = [
        SimpleNamespace(scalar_one_or_none=lambda: user),  # get_current_user
        SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace() if has_access else None
        ),  # require_campaign_access
    ]
    session = AsyncMock()

    async def _execute(*args, **kwargs):
        return responses.pop(0)

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _override_session(session) -> None:
    async def _fake():
        yield session

    dashboard_app.app.dependency_overrides[get_db_session] = _fake


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------


class TestUnauthenticated:
    def test_daily_dates_without_cookie_returns_401(
        self, client: TestClient
    ) -> None:
        session = AsyncMock()
        _override_session(session)
        response = client.get(f"/api/campaigns/{uuid4()}/reports/daily")
        assert response.status_code == 401

    def test_weekly_index_without_cookie_returns_401(
        self, client: TestClient
    ) -> None:
        session = AsyncMock()
        _override_session(session)
        response = client.get(f"/api/campaigns/{uuid4()}/reports/weekly")
        assert response.status_code == 401

    def test_experiments_without_cookie_returns_401(
        self, client: TestClient
    ) -> None:
        session = AsyncMock()
        _override_session(session)
        response = client.get(f"/api/campaigns/{uuid4()}/experiments")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


class TestCrossUserIsolation:
    def test_foreign_campaign_returns_404(self, client: TestClient) -> None:
        """User A requesting a campaign only User B owns must see 404."""
        user = _make_user()
        foreign_campaign_id = uuid4()

        session = _authed_session_with_membership(user, has_access=False)
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            response = client.get(
                f"/api/campaigns/{foreign_campaign_id}/reports/daily"
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 404
        # Generic "not found" so we never leak existence.
        assert "not found" in response.json()["detail"].lower()

    def test_owned_campaign_flows_through(self, client: TestClient) -> None:
        """A user who owns the campaign passes the gate and reaches the handler."""
        user = _make_user()
        campaign_id = uuid4()

        session = _authed_session_with_membership(user, has_access=True)
        # The daily-dates endpoint runs one more .execute() for its SQL;
        # extend the queue with an empty fetchall.
        original_execute = session.execute.side_effect

        call_count = [0]

        async def _execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                # First two calls: user + membership check
                return await _make_response(call_count[0], user, True)
            # Third call: the daily-dates SQL
            return SimpleNamespace(fetchall=lambda: [])

        async def _make_response(n, user, has_access):
            if n == 1:
                return SimpleNamespace(scalar_one_or_none=lambda: user)
            return SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace() if has_access else None
            )

        session.execute = AsyncMock(side_effect=_execute)
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            response = client.get(
                f"/api/campaigns/{campaign_id}/reports/daily"
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 200
        assert response.json() == {"dates": []}


# ---------------------------------------------------------------------------
# CSRF enforcement on mutating experiment endpoints
# ---------------------------------------------------------------------------


class TestExperimentsCsrf:
    def test_approve_without_csrf_returns_403(self, client: TestClient) -> None:
        user = _make_user()
        campaign_id = uuid4()
        approval_id = uuid4()

        session = _authed_session_with_membership(user, has_access=True)
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            response = client.post(
                f"/api/campaigns/{campaign_id}/experiments/{approval_id}/approve"
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 403
        assert "csrf" in response.json()["detail"].lower()

    def test_reject_without_csrf_returns_403(self, client: TestClient) -> None:
        user = _make_user()
        campaign_id = uuid4()
        approval_id = uuid4()

        session = _authed_session_with_membership(user, has_access=True)
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            response = client.post(
                f"/api/campaigns/{campaign_id}/experiments/{approval_id}/reject",
                json={"reason": "bad fit"},
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 403

    def test_suggest_without_csrf_returns_403(self, client: TestClient) -> None:
        user = _make_user()
        campaign_id = uuid4()

        session = _authed_session_with_membership(user, has_access=True)
        _override_session(session)

        token = create_session_token(user.id)
        client.cookies.set("session_token", token)
        try:
            response = client.post(
                f"/api/campaigns/{campaign_id}/experiments/suggest",
                json={"slot_name": "headline", "slot_value": "Try now"},
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 403
