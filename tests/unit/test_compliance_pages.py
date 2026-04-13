"""Tests for Meta compliance pages: privacy policy, data deletion, deauth webhook."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


APP_SECRET = "test-secret-for-compliance"


def _make_signed_request(
    payload: dict,
    secret: str = APP_SECRET,
) -> str:
    """Build a Meta-style signed_request string."""
    payload_bytes = json.dumps(payload).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sig = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded_sig = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{encoded_sig}.{encoded_payload}"


class TestPrivacyPage:
    """The /privacy page must be publicly accessible."""

    def test_returns_200_without_auth(self, client: TestClient) -> None:
        response = client.get("/privacy")
        assert response.status_code == 200

    def test_contains_privacy_heading(self, client: TestClient) -> None:
        response = client.get("/privacy")
        assert "Privacy Policy" in response.text

    def test_contains_meta_section(self, client: TestClient) -> None:
        response = client.get("/privacy")
        assert "Meta" in response.text
        assert "OAuth" in response.text or "access token" in response.text

    def test_contains_data_deletion_section(self, client: TestClient) -> None:
        response = client.get("/privacy")
        assert "Data deletion" in response.text or "data deletion" in response.text

    def test_contains_contact_email(self, client: TestClient) -> None:
        response = client.get("/privacy")
        # Should contain the default report_email_from
        assert "@" in response.text


class TestDataDeletionStatusPage:
    """The /data-deletion/{code} page serves deletion confirmations."""

    def test_valid_code_returns_200(self, client: TestClient) -> None:
        fake_deletion = SimpleNamespace(
            confirmation_code="abc123",
            meta_user_id="99999",
            status="completed",
            requested_at=datetime(2026, 4, 13, 12, 0, 0, tzinfo=UTC),
        )
        with patch(
            "src.dashboard.app.get_data_deletion_request",
            new=AsyncMock(return_value=fake_deletion),
        ):
            response = client.get("/data-deletion/abc123")

        assert response.status_code == 200
        assert "abc123" in response.text
        assert "completed" in response.text.lower()

    def test_invalid_code_returns_404(self, client: TestClient) -> None:
        with patch(
            "src.dashboard.app.get_data_deletion_request",
            new=AsyncMock(return_value=None),
        ):
            response = client.get("/data-deletion/nonexistent")

        assert response.status_code == 404


class TestDeauthorizeWebhook:
    """POST /api/webhooks/meta/deauthorize handles Meta's signed callback."""

    def test_valid_signed_request_deletes_connection(self, client: TestClient) -> None:
        user_id = uuid.uuid4()
        signed = _make_signed_request(
            {"algorithm": "HMAC-SHA256", "user_id": "12345"},
            secret=APP_SECRET,
        )

        fake_deletion = SimpleNamespace(
            id=uuid.uuid4(),
            confirmation_code="test-code-xyz",
        )

        with (
            patch(
                "src.dashboard.app.get_settings",
                return_value=SimpleNamespace(
                    meta_app_secret=APP_SECRET,
                    api_base_url="https://app.example.com",
                    report_email_from="test@example.com",
                ),
            ),
            patch(
                "src.dashboard.app.delete_meta_connection_by_meta_user_id",
                new=AsyncMock(return_value=user_id),
            ) as delete_mock,
            patch(
                "src.dashboard.app.create_data_deletion_request",
                new=AsyncMock(return_value=fake_deletion),
            ),
        ):
            response = client.post(
                "/api/webhooks/meta/deauthorize",
                data={"signed_request": signed},
            )

        assert response.status_code == 200
        body = response.json()
        assert "url" in body
        assert "confirmation_code" in body
        assert body["url"].startswith("https://app.example.com/data-deletion/")

        delete_mock.assert_awaited_once()
        # Verify the meta_user_id argument (second positional arg after session)
        call_args = delete_mock.await_args
        assert call_args[0][1] == "12345"

    def test_missing_signed_request_returns_400(self, client: TestClient) -> None:
        with patch(
            "src.dashboard.app.get_settings",
            return_value=SimpleNamespace(meta_app_secret=APP_SECRET),
        ):
            response = client.post("/api/webhooks/meta/deauthorize", data={})

        assert response.status_code == 400

    def test_tampered_signature_returns_403(self, client: TestClient) -> None:
        # Build a valid signed request with a different secret
        signed = _make_signed_request(
            {"algorithm": "HMAC-SHA256", "user_id": "12345"},
            secret="wrong-secret",
        )

        with patch(
            "src.dashboard.app.get_settings",
            return_value=SimpleNamespace(meta_app_secret=APP_SECRET),
        ):
            response = client.post(
                "/api/webhooks/meta/deauthorize",
                data={"signed_request": signed},
            )

        assert response.status_code == 403

    def test_no_app_secret_configured_returns_500(self, client: TestClient) -> None:
        with patch(
            "src.dashboard.app.get_settings",
            return_value=SimpleNamespace(meta_app_secret=""),
        ):
            response = client.post(
                "/api/webhooks/meta/deauthorize",
                data={"signed_request": "anything"},
            )

        assert response.status_code == 500

    def test_unknown_meta_user_still_logs_deletion(self, client: TestClient) -> None:
        """Even if Meta user ID doesn't match any connection, we log it."""
        signed = _make_signed_request(
            {"algorithm": "HMAC-SHA256", "user_id": "unknown999"},
            secret=APP_SECRET,
        )

        fake_deletion = SimpleNamespace(
            id=uuid.uuid4(),
            confirmation_code="orphan-code",
        )

        with (
            patch(
                "src.dashboard.app.get_settings",
                return_value=SimpleNamespace(
                    meta_app_secret=APP_SECRET,
                    api_base_url="https://app.example.com",
                    report_email_from="test@example.com",
                ),
            ),
            patch(
                "src.dashboard.app.delete_meta_connection_by_meta_user_id",
                new=AsyncMock(return_value=None),  # no matching connection
            ),
            patch(
                "src.dashboard.app.create_data_deletion_request",
                new=AsyncMock(return_value=fake_deletion),
            ) as create_mock,
        ):
            response = client.post(
                "/api/webhooks/meta/deauthorize",
                data={"signed_request": signed},
            )

        assert response.status_code == 200
        # Should still create a deletion request with user_id=None
        create_mock.assert_awaited_once()
        call_kwargs = create_mock.await_args.kwargs
        assert call_kwargs["user_id"] is None
        assert call_kwargs["meta_user_id"] == "unknown999"
