"""Unit tests verifying that GET API endpoints require authentication.

Covers the seven endpoints locked down in the security hardening pass:
- /api/campaigns
- /api/campaigns/{id}/variants
- /api/campaigns/{id}/elements
- /api/campaigns/{id}/interactions
- /api/campaigns/{id}/cycles
- /api/gene-pool
- /api/approvals
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


CAMPAIGN_ID = str(uuid.uuid4())


class TestUnauthenticatedReturns401:
    """Every secured GET endpoint must return 401 without a session cookie."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/campaigns",
            f"/api/campaigns/{CAMPAIGN_ID}/variants",
            f"/api/campaigns/{CAMPAIGN_ID}/elements",
            f"/api/campaigns/{CAMPAIGN_ID}/interactions",
            f"/api/campaigns/{CAMPAIGN_ID}/cycles",
            "/api/gene-pool",
            "/api/approvals",
        ],
    )
    def test_no_cookie_returns_401(self, client: TestClient, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 401, f"{path} returned {response.status_code}"


class TestCampaignScopedAccess:
    """Campaign-scoped endpoints return 404 when user lacks access."""

    def test_variants_returns_404_for_unowned_campaign(self, client: TestClient) -> None:
        from fastapi import HTTPException

        from src.dashboard.deps import get_current_user, require_campaign_access

        # Simulate an authenticated user who does NOT own the campaign.
        # Override require_campaign_access to raise 404 directly, which
        # is what the real dependency does when user_campaigns has no row.
        async def _fake_user():
            return SimpleNamespace(id=uuid.uuid4(), is_active=True)

        async def _deny_access():
            raise HTTPException(status_code=404, detail="not found")

        app.dependency_overrides[get_current_user] = _fake_user
        app.dependency_overrides[require_campaign_access] = _deny_access
        try:
            cid = str(uuid.uuid4())
            response = client.get(f"/api/campaigns/{cid}/variants")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
