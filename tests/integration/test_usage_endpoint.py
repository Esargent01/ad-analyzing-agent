"""Tests for ``GET /api/me/usage`` — per-user cost rollup.

The endpoint stitches four aggregation queries together and we don't
hit a real DB here; we stub ``session.execute`` to return scripted
rows for each SQL call in order:

1. totals (``.one()``)
2. by_service (``.fetchall()``)
3. by_campaign (``.fetchall()``)
4. by_day (``.fetchall()``)

This lets us test the endpoint's request plumbing (auth, range
validation, Decimal rendering, Pydantic shape) without depending on
a Postgres / TimescaleDB instance.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dashboard_app
from src.dashboard.auth import create_session_token
from src.dashboard.deps import get_db_session


# ---------------------------------------------------------------------------
# Test client + session-stub helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(dashboard_app.app)
    yield c
    dashboard_app.app.dependency_overrides.clear()


def _make_user(email: str = "alice@example.com"):
    return SimpleNamespace(id=uuid4(), email=email, is_active=True)


def _override_session(session) -> None:
    async def _fake():
        yield session

    dashboard_app.app.dependency_overrides[get_db_session] = _fake


def _build_session(
    user,
    *,
    totals_row,
    service_rows,
    campaign_rows,
    day_rows,
) -> AsyncMock:
    """Return an AsyncMock session that scripts 5 .execute() calls.

    Order matches the actual request flow:
    1. ``get_current_user`` selects the user → ``scalar_one_or_none``
    2. totals SELECT → ``.one()``
    3. by_service SELECT → ``.fetchall()``
    4. by_campaign SELECT → ``.fetchall()``
    5. by_day SELECT → ``.fetchall()``
    """
    queue = [
        SimpleNamespace(scalar_one_or_none=lambda: user),
        SimpleNamespace(one=lambda: totals_row),
        SimpleNamespace(fetchall=lambda: list(service_rows)),
        SimpleNamespace(fetchall=lambda: list(campaign_rows)),
        SimpleNamespace(fetchall=lambda: list(day_rows)),
    ]
    session = AsyncMock()

    async def _execute(*args, **kwargs):
        if not queue:
            raise AssertionError("unexpected extra session.execute call")
        return queue.pop(0)

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _sign_in(client: TestClient, user) -> None:
    token = create_session_token(user.id)
    client.cookies.set("session_token", token)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_without_cookie_returns_401(self, client: TestClient) -> None:
        _override_session(AsyncMock())
        response = client.get("/api/me/usage")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Happy path: all four rollups resolved
# ---------------------------------------------------------------------------


class TestUsageHappyPath:
    def test_returns_full_rollup_with_decimal_math(
        self, client: TestClient
    ) -> None:
        user = _make_user()
        campaign_a = uuid4()
        campaign_b = uuid4()

        totals_row = SimpleNamespace(
            total_cost=Decimal("0.125000"),
            total_calls=7,
        )
        service_rows = [
            SimpleNamespace(service="llm", cost=Decimal("0.120000"), calls=5),
            SimpleNamespace(service="meta_api", cost=Decimal("0.005000"), calls=2),
        ]
        campaign_rows = [
            SimpleNamespace(
                campaign_id=campaign_a,
                campaign_name="Spring Launch",
                cost=Decimal("0.100000"),
                calls=4,
            ),
            SimpleNamespace(
                campaign_id=campaign_b,
                campaign_name="Retargeting",
                cost=Decimal("0.025000"),
                calls=3,
            ),
        ]
        day_rows = [
            SimpleNamespace(
                day=date(2026, 4, 1),
                cost=Decimal("0.050000"),
                calls=3,
            ),
            SimpleNamespace(
                day=date(2026, 4, 2),
                cost=Decimal("0.075000"),
                calls=4,
            ),
        ]

        session = _build_session(
            user,
            totals_row=totals_row,
            service_rows=service_rows,
            campaign_rows=campaign_rows,
            day_rows=day_rows,
        )
        _override_session(session)

        _sign_in(client, user)
        try:
            response = client.get(
                "/api/me/usage?from=2026-04-01&to=2026-04-02"
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["from_date"] == "2026-04-01"
        assert body["to_date"] == "2026-04-02"
        assert Decimal(body["total_cost_usd"]) == Decimal("0.125000")
        assert body["total_calls"] == 7

        assert body["by_service"] == [
            {"service": "llm", "cost_usd": "0.120000", "calls": 5},
            {"service": "meta_api", "cost_usd": "0.005000", "calls": 2},
        ]

        assert body["by_campaign"][0]["campaign_id"] == str(campaign_a)
        assert body["by_campaign"][0]["campaign_name"] == "Spring Launch"
        assert Decimal(body["by_campaign"][0]["cost_usd"]) == Decimal("0.100000")
        assert body["by_campaign"][0]["calls"] == 4
        assert body["by_campaign"][1]["campaign_id"] == str(campaign_b)

        assert [d["day"] for d in body["by_day"]] == [
            "2026-04-01",
            "2026-04-02",
        ]
        assert Decimal(body["by_day"][1]["cost_usd"]) == Decimal("0.075000")

    def test_null_campaign_bucket_is_preserved(
        self, client: TestClient
    ) -> None:
        """Rows with a NULL campaign_id (e.g., copywriter run without a
        campaign) must still appear in the by_campaign breakdown with
        ``campaign_id: null``."""
        user = _make_user()
        totals_row = SimpleNamespace(
            total_cost=Decimal("0.010000"), total_calls=1
        )
        service_rows = [
            SimpleNamespace(service="llm", cost=Decimal("0.010000"), calls=1),
        ]
        campaign_rows = [
            SimpleNamespace(
                campaign_id=None,
                campaign_name=None,
                cost=Decimal("0.010000"),
                calls=1,
            ),
        ]
        day_rows = [
            SimpleNamespace(
                day=date(2026, 4, 5),
                cost=Decimal("0.010000"),
                calls=1,
            ),
        ]

        session = _build_session(
            user,
            totals_row=totals_row,
            service_rows=service_rows,
            campaign_rows=campaign_rows,
            day_rows=day_rows,
        )
        _override_session(session)

        _sign_in(client, user)
        try:
            response = client.get("/api/me/usage?from=2026-04-05&to=2026-04-05")
        finally:
            client.cookies.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["by_campaign"] == [
            {
                "campaign_id": None,
                "campaign_name": None,
                "cost_usd": "0.010000",
                "calls": 1,
            }
        ]

    def test_empty_window_returns_zero_totals(
        self, client: TestClient
    ) -> None:
        user = _make_user()

        session = _build_session(
            user,
            totals_row=SimpleNamespace(total_cost=Decimal("0"), total_calls=0),
            service_rows=[],
            campaign_rows=[],
            day_rows=[],
        )
        _override_session(session)

        _sign_in(client, user)
        try:
            response = client.get("/api/me/usage?from=2026-04-01&to=2026-04-01")
        finally:
            client.cookies.clear()

        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["total_cost_usd"]) == Decimal("0")
        assert body["total_calls"] == 0
        assert body["by_service"] == []
        assert body["by_campaign"] == []
        assert body["by_day"] == []


# ---------------------------------------------------------------------------
# Default window: last 30 days when neither from nor to supplied
# ---------------------------------------------------------------------------


class TestDefaultWindow:
    def test_default_range_is_trailing_30_days(
        self, client: TestClient
    ) -> None:
        user = _make_user()

        session = _build_session(
            user,
            totals_row=SimpleNamespace(total_cost=Decimal("0"), total_calls=0),
            service_rows=[],
            campaign_rows=[],
            day_rows=[],
        )
        _override_session(session)

        _sign_in(client, user)
        try:
            response = client.get("/api/me/usage")
        finally:
            client.cookies.clear()

        assert response.status_code == 200
        body = response.json()

        today = datetime.now(timezone.utc).date()
        expected_from = today - timedelta(days=29)
        assert body["from_date"] == expected_from.isoformat()
        assert body["to_date"] == today.isoformat()


# ---------------------------------------------------------------------------
# Range validation
# ---------------------------------------------------------------------------


class TestRangeValidation:
    def test_inverted_range_returns_400(self, client: TestClient) -> None:
        user = _make_user()
        # Only the user-lookup execute happens before we reject.
        queue = [SimpleNamespace(scalar_one_or_none=lambda: user)]
        session = AsyncMock()

        async def _execute(*args, **kwargs):
            return queue.pop(0)

        session.execute = AsyncMock(side_effect=_execute)
        _override_session(session)

        _sign_in(client, user)
        try:
            response = client.get("/api/me/usage?from=2026-04-10&to=2026-04-01")
        finally:
            client.cookies.clear()

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "invalid_range"

    def test_range_too_large_returns_400(self, client: TestClient) -> None:
        user = _make_user()
        queue = [SimpleNamespace(scalar_one_or_none=lambda: user)]
        session = AsyncMock()

        async def _execute(*args, **kwargs):
            return queue.pop(0)

        session.execute = AsyncMock(side_effect=_execute)
        _override_session(session)

        _sign_in(client, user)
        try:
            response = client.get(
                "/api/me/usage?from=2024-01-01&to=2026-01-01"
            )
        finally:
            client.cookies.clear()

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "range_too_large"
