"""Fernet wrapper for at-rest encryption of Meta access tokens.

Meta OAuth gives us a 60-day long-lived access token per user. Storing
it in plaintext is unacceptable — a leaked DB dump would yield cross-
customer ad-account access. We symmetric-encrypt with
``cryptography.fernet`` using a single app-wide key loaded once from
``settings.meta_token_encryption_key``.

**Losing the key = losing every stored connection.** Back it up in
1Password / AWS Secrets Manager. If the key is ever rotated, every
connected user has to re-OAuth; there is deliberately no two-key
rollover dance in Phase B.

Generate a fresh key with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from src.config import get_settings


class MetaTokenCryptoError(RuntimeError):
    """Raised when the encryption key is missing or invalid."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Return a cached ``Fernet`` instance built from the settings key.

    Raises :class:`MetaTokenCryptoError` at first use if the key is
    empty or malformed — we fail fast rather than silently storing
    un-decryptable blobs. Cached so the (relatively expensive) key
    derivation runs once per process.
    """
    key = get_settings().meta_token_encryption_key
    if not key:
        raise MetaTokenCryptoError(
            "META_TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'` and add it to .env."
        )
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise MetaTokenCryptoError(
            "META_TOKEN_ENCRYPTION_KEY is not a valid Fernet key. "
            "It must be a 32-byte url-safe base64-encoded string."
        ) from exc


def encrypt_token(plaintext: str) -> str:
    """Encrypt a Meta access token for storage.

    Returns a URL-safe base64 string (Fernet's native format) suitable
    for a ``TEXT`` column. The output embeds a timestamp and random IV,
    so re-encrypting the same plaintext yields a different ciphertext.
    """
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("plaintext must be a non-empty string")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a previously-stored Meta access token.

    Raises :class:`MetaTokenCryptoError` on bad key, tampered
    ciphertext, or truncated input.
    """
    if not isinstance(ciphertext, str) or not ciphertext:
        raise ValueError("ciphertext must be a non-empty string")
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise MetaTokenCryptoError(
            "failed to decrypt meta token — key mismatch or tampered ciphertext"
        ) from exc
