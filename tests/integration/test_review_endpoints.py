"""Integration tests for the weekly review FastAPI endpoints.

These tests mock the database layer and query functions so we can drive
the endpoints without a running Postgres instance. The goal is to verify
routing, token verification, and the happy/error paths.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dashboard_app
from src.dashboard.tokens import create_review_token


@pytest.fixture()
def client() -> TestClient:
    return TestClient(dashboard_app.app)


@pytest.fixture()
def valid_token_and_campaign() -> tuple[str, uuid.UUID]:
    campaign_id = uuid.uuid4()
    token = create_review_token(campaign_id)
    return token, campaign_id


@asynccontextmanager
async def _fake_session_cm():
    """Context manager yielding a fresh AsyncMock session."""
    session = AsyncMock()
    yield session


def _patch_session():
    """Patch get_session in the dashboard app to yield a mock session."""
    return patch(
        "src.dashboard.app.get_session",
        new=lambda: _fake_session_cm(),
    )


class TestReviewPageGet:
    """GET /review/{token}"""

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        response = client.get("/review/not-a-token")
        assert response.status_code == 401
        assert "expired" in response.text.lower() or "invalid" in response.text.lower()

    def test_valid_token_renders_review_page(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, campaign_id = valid_token_and_campaign

        fake_campaign = SimpleNamespace(
            id=campaign_id,
            name="Spring Sale",
        )
        fake_proposed = [
            SimpleNamespace(
                approval_id=uuid.uuid4(),
                variant_id=uuid.uuid4(),
                variant_code="V42",
                genome={"headline": "Save big", "cta_text": "Shop now"},
                genome_summary="Save big · Shop now",
                hypothesis="Urgency messaging drives CTR",
                submitted_at=None,
                classification="new",
                days_until_expiry=14,
            )
        ]

        with (
            _patch_session(),
            patch(
                "src.dashboard.app._get_campaign_light",
                new=AsyncMock(return_value=fake_campaign),
            ),
            patch(
                "src.dashboard.app.load_proposed_variants",
                new=AsyncMock(return_value=fake_proposed),
            ),
            patch(
                "src.dashboard.app.list_gene_pool_entries",
                new=AsyncMock(return_value=[]),
            ),
        ):
            response = client.get(f"/review/{token}")

        assert response.status_code == 200
        assert "Spring Sale" in response.text
        assert "V42" in response.text
        assert "Save big" in response.text

    def test_valid_token_missing_campaign_returns_404(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign

        with (
            _patch_session(),
            patch(
                "src.dashboard.app._get_campaign_light",
                new=AsyncMock(return_value=None),
            ),
        ):
            response = client.get(f"/review/{token}")

        assert response.status_code == 404


class TestApproveEndpoint:
    """POST /api/approvals/{id}/approve"""

    def test_missing_token_returns_422(self, client: TestClient) -> None:
        approval_id = str(uuid.uuid4())
        response = client.post(f"/api/approvals/{approval_id}/approve")
        assert response.status_code == 422  # missing required form field

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        approval_id = str(uuid.uuid4())
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            data={"token": "not-valid"},
        )
        assert response.status_code == 401

    def test_invalid_uuid_returns_400(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        response = client.post(
            "/api/approvals/not-a-uuid/approve",
            data={"token": token},
        )
        assert response.status_code == 400

    def test_approval_not_found_returns_404(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        approval_id = str(uuid.uuid4())

        with (
            _patch_session(),
            patch(
                "src.dashboard.app._load_approval_or_404",
                new=AsyncMock(
                    side_effect=dashboard_app.HTTPException(
                        status_code=404, detail="Approval not found"
                    )
                ),
            ),
        ):
            response = client.post(
                f"/api/approvals/{approval_id}/approve",
                data={"token": token},
            )

        assert response.status_code == 404

    def test_happy_path_returns_approved(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        approval_id = str(uuid.uuid4())

        with (
            _patch_session(),
            patch(
                "src.dashboard.app._load_approval_or_404",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.dashboard.app.approve_variant",
                new=AsyncMock(return_value=SimpleNamespace(id=uuid.UUID(approval_id))),
            ),
        ):
            response = client.post(
                f"/api/approvals/{approval_id}/approve",
                data={"token": token},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"
        assert body["approval_id"] == approval_id


class TestRejectEndpoint:
    """POST /api/approvals/{id}/reject"""

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        approval_id = str(uuid.uuid4())
        response = client.post(
            f"/api/approvals/{approval_id}/reject",
            data={"token": "invalid"},
        )
        assert response.status_code == 401

    def test_happy_path_returns_rejected(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        approval_id = str(uuid.uuid4())

        with (
            _patch_session(),
            patch(
                "src.dashboard.app._load_approval_or_404",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.dashboard.app.reject_variant",
                new=AsyncMock(return_value=SimpleNamespace(id=uuid.UUID(approval_id))),
            ),
        ):
            response = client.post(
                f"/api/approvals/{approval_id}/reject",
                data={"token": token, "reason": "off_brand"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "rejected"


class TestSuggestGenePoolEndpoint:
    """POST /api/gene-pool/suggest"""

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/gene-pool/suggest",
            data={"token": "nope", "slot_name": "headline", "slot_value": "Hi"},
        )
        assert response.status_code == 401

    def test_disallowed_slot_returns_400(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        response = client.post(
            "/api/gene-pool/suggest",
            data={
                "token": token,
                "slot_name": "media_asset",  # not allowed
                "slot_value": "cool_video.mov",
            },
        )
        assert response.status_code == 400

    def test_empty_value_returns_400(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        response = client.post(
            "/api/gene-pool/suggest",
            data={
                "token": token,
                "slot_name": "headline",
                "slot_value": "   ",
            },
        )
        assert response.status_code == 400

    def test_too_long_value_returns_400(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        response = client.post(
            "/api/gene-pool/suggest",
            data={
                "token": token,
                "slot_name": "headline",
                "slot_value": "x" * 501,
            },
        )
        assert response.status_code == 400

    def test_happy_path_adds_entry(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign
        fake_entry = SimpleNamespace(
            slot_name="headline",
            slot_value="Save 50% today only",
        )

        with (
            _patch_session(),
            patch(
                "src.dashboard.app.add_gene_pool_entry",
                new=AsyncMock(return_value=fake_entry),
            ),
        ):
            response = client.post(
                "/api/gene-pool/suggest",
                data={
                    "token": token,
                    "slot_name": "headline",
                    "slot_value": "Save 50% today only",
                    "description": "Clean urgency angle",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "added"
        assert body["slot_name"] == "headline"
        assert body["slot_value"] == "Save 50% today only"

    def test_duplicate_returns_409(
        self,
        client: TestClient,
        valid_token_and_campaign: tuple[str, uuid.UUID],
    ) -> None:
        token, _ = valid_token_and_campaign

        with (
            _patch_session(),
            patch(
                "src.dashboard.app.add_gene_pool_entry",
                new=AsyncMock(side_effect=Exception("duplicate key")),
            ),
        ):
            response = client.post(
                "/api/gene-pool/suggest",
                data={
                    "token": token,
                    "slot_name": "headline",
                    "slot_value": "Already exists",
                },
            )

        assert response.status_code == 409
