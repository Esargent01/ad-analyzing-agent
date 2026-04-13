"""Tests for Meta deauthorization webhook: signed-request verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from src.dashboard.meta_webhooks import (
    generate_confirmation_code,
    parse_signed_request,
)

APP_SECRET = "test-app-secret-12345"


def _make_signed_request(
    payload: dict,
    secret: str = APP_SECRET,
    *,
    tamper_sig: bool = False,
) -> str:
    """Build a Meta-style signed_request string."""
    payload_bytes = json.dumps(payload).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")

    sig = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if tamper_sig:
        sig = b"\x00" * len(sig)

    encoded_sig = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{encoded_sig}.{encoded_payload}"


class TestParseSignedRequest:
    """Tests for parse_signed_request()."""

    def test_valid_signed_request(self) -> None:
        payload = {"algorithm": "HMAC-SHA256", "user_id": "123456"}
        signed = _make_signed_request(payload)

        result = parse_signed_request(signed, APP_SECRET)

        assert result.user_id == "123456"
        assert result.algorithm == "HMAC-SHA256"

    def test_integer_user_id_coerced_to_string(self) -> None:
        payload = {"algorithm": "HMAC-SHA256", "user_id": 789012}
        signed = _make_signed_request(payload)

        result = parse_signed_request(signed, APP_SECRET)
        assert result.user_id == "789012"

    def test_tampered_signature_rejected(self) -> None:
        payload = {"algorithm": "HMAC-SHA256", "user_id": "123456"}
        signed = _make_signed_request(payload, tamper_sig=True)

        with pytest.raises(ValueError, match="Invalid signature"):
            parse_signed_request(signed, APP_SECRET)

    def test_wrong_secret_rejected(self) -> None:
        payload = {"algorithm": "HMAC-SHA256", "user_id": "123456"}
        signed = _make_signed_request(payload, secret=APP_SECRET)

        with pytest.raises(ValueError, match="Invalid signature"):
            parse_signed_request(signed, "wrong-secret")

    def test_unsupported_algorithm_rejected(self) -> None:
        payload = {"algorithm": "MD5", "user_id": "123456"}
        signed = _make_signed_request(payload)

        with pytest.raises(ValueError, match="Unsupported algorithm"):
            parse_signed_request(signed, APP_SECRET)

    def test_missing_user_id_rejected(self) -> None:
        payload = {"algorithm": "HMAC-SHA256"}
        signed = _make_signed_request(payload)

        with pytest.raises(ValueError, match="missing user_id"):
            parse_signed_request(signed, APP_SECRET)

    def test_no_dot_separator_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            parse_signed_request("nodothere", APP_SECRET)

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            parse_signed_request("", APP_SECRET)


class TestGenerateConfirmationCode:
    """Tests for generate_confirmation_code()."""

    def test_returns_string(self) -> None:
        code = generate_confirmation_code()
        assert isinstance(code, str)
        assert len(code) > 10

    def test_unique_across_calls(self) -> None:
        codes = {generate_confirmation_code() for _ in range(50)}
        assert len(codes) == 50
