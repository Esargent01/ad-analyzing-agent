"""Meta Platform webhook handlers: deauthorize callback + signed-request verification.

When a user removes the app from their Facebook account settings,
Meta sends a POST to the **Deauthorization Callback URL** configured
in the Meta App Dashboard.  The payload is a *signed request* — a
base64url-encoded JSON blob signed with the app secret via HMAC-SHA256.

This module:

1. Verifies the signed request (rejects tampered payloads).
2. Deletes the matching ``UserMetaConnection`` row.
3. Records a ``DataDeletionRequest`` so we can serve a status page
   at ``/data-deletion/{confirmation_code}`` — Meta's required
   response format.

References
----------
- https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
- https://developers.facebook.com/docs/facebook-login/security/#signed-request
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignedRequestPayload:
    """Parsed fields from a verified Meta signed request."""

    user_id: str
    algorithm: str


def parse_signed_request(signed_request: str, app_secret: str) -> SignedRequestPayload:
    """Verify and decode a Meta signed request.

    Parameters
    ----------
    signed_request:
        The ``signed_request`` form field from Meta's POST.
    app_secret:
        The Meta App Secret used for HMAC verification.

    Returns
    -------
    SignedRequestPayload with the Meta user ID.

    Raises
    ------
    ValueError
        If the signature is invalid or the payload is malformed.
    """
    try:
        encoded_sig, encoded_payload = signed_request.split(".", 1)
    except ValueError as exc:
        raise ValueError("signed_request must contain exactly one '.'") from exc

    # Decode signature
    sig = base64.urlsafe_b64decode(encoded_sig + "==")

    # Decode payload
    payload_bytes = base64.urlsafe_b64decode(encoded_payload + "==")
    payload = json.loads(payload_bytes)

    algorithm = payload.get("algorithm", "").upper()
    if algorithm != "HMAC-SHA256":
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    # Verify HMAC
    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Invalid signature — request may be tampered")

    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("Payload missing user_id")

    return SignedRequestPayload(user_id=str(user_id), algorithm=algorithm)


def generate_confirmation_code() -> str:
    """Generate a URL-safe confirmation code for data deletion tracking."""
    return secrets.token_urlsafe(16)
