"""Tests for HMAC-signed review tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from src.dashboard.tokens import create_review_token, verify_review_token


class TestReviewTokens:
    """Round-trip and tamper/expiry tests for review tokens."""

    def test_sign_verify_round_trip(self) -> None:
        """Creating and verifying a fresh token returns the same campaign_id."""
        campaign_id = uuid4()
        token = create_review_token(campaign_id)
        verified = verify_review_token(token)
        assert verified == campaign_id

    def test_verify_rejects_garbage(self) -> None:
        """Arbitrary strings should not verify."""
        assert verify_review_token("not-a-real-token") is None

    def test_verify_rejects_empty_string(self) -> None:
        assert verify_review_token("") is None

    def test_verify_rejects_tampered_signature(self) -> None:
        """Flipping a bit in the signature invalidates the token."""
        campaign_id = uuid4()
        token = create_review_token(campaign_id)
        # Mutate the last char to guarantee a different signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert verify_review_token(tampered) is None

    def test_verify_rejects_expired_token(self) -> None:
        """A token past its expiry date should not verify."""
        campaign_id = uuid4()
        # Create token with TTL of 1 day, then simulate 2 days passing
        token = create_review_token(campaign_id, ttl_days=1)

        future = datetime.now(timezone.utc) + timedelta(days=2)

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future if tz is None else future.astimezone(tz)

        with patch("src.dashboard.tokens.datetime", _FakeDatetime):
            assert verify_review_token(token) is None

    def test_verify_accepts_just_before_expiry(self) -> None:
        """A token still within its TTL should verify."""
        campaign_id = uuid4()
        token = create_review_token(campaign_id, ttl_days=7)
        assert verify_review_token(token) == campaign_id

    def test_different_campaigns_produce_different_tokens(self) -> None:
        """Two fresh tokens for different campaigns must differ."""
        token_a = create_review_token(uuid4())
        token_b = create_review_token(uuid4())
        assert token_a != token_b

    def test_verify_returns_uuid_type(self) -> None:
        """verify_review_token returns a UUID instance (not a string)."""
        campaign_id = uuid4()
        token = create_review_token(campaign_id)
        verified = verify_review_token(token)
        assert isinstance(verified, UUID)

    def test_token_is_urlsafe(self) -> None:
        """Tokens should only contain URL-safe base64 characters."""
        import string

        token = create_review_token(uuid4())
        allowed = set(string.ascii_letters + string.digits + "-_")
        assert set(token).issubset(allowed)

    def test_verify_rejects_malformed_payload(self) -> None:
        """A valid base64 string that doesn't contain a proper payload should fail."""
        import base64

        # Only one colon, not the required three fields
        raw = "not-a-uuid:12345"
        token = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        assert verify_review_token(token) is None


@pytest.mark.parametrize("ttl_days", [1, 7, 14, 30])
def test_varying_ttl_round_trip(ttl_days: int) -> None:
    """Token round-trip should work for any reasonable TTL."""
    campaign_id = uuid4()
    token = create_review_token(campaign_id, ttl_days=ttl_days)
    assert verify_review_token(token) == campaign_id
