"""Unit tests for ``src.dashboard.crypto`` (Fernet token wrapper).

Exercises round-trip encryption, non-determinism (Fernet embeds a
timestamp + IV), and the failure modes: missing key, malformed key,
and decryption with the wrong key. The ``_get_fernet`` cache is
cleared between tests so each one gets a fresh read of the settings
module.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from src.dashboard import crypto


def _fresh_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    """Drop the module-level LRU cache so tests don't leak keys."""
    crypto._get_fernet.cache_clear()
    yield
    crypto._get_fernet.cache_clear()


class TestEncryptRoundTrip:
    def test_round_trip_preserves_plaintext(self) -> None:
        key = _fresh_key()
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": key})(),
        ):
            cipher = crypto.encrypt_token("super-secret-meta-token")
            assert crypto.decrypt_token(cipher) == "super-secret-meta-token"

    def test_encryption_is_non_deterministic(self) -> None:
        """Fernet embeds a timestamp + random IV, so same plaintext → different ciphertext."""
        key = _fresh_key()
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": key})(),
        ):
            a = crypto.encrypt_token("same-input")
            b = crypto.encrypt_token("same-input")
            assert a != b
            # Both must still decrypt to the same plaintext.
            assert crypto.decrypt_token(a) == crypto.decrypt_token(b) == "same-input"


class TestFailureModes:
    def test_missing_key_raises(self) -> None:
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": ""})(),
        ):
            with pytest.raises(crypto.MetaTokenCryptoError, match="not set"):
                crypto.encrypt_token("anything")

    def test_malformed_key_raises(self) -> None:
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": "not-a-fernet-key"})(),
        ):
            with pytest.raises(crypto.MetaTokenCryptoError, match="not a valid"):
                crypto.encrypt_token("anything")

    def test_decrypt_with_wrong_key_raises(self) -> None:
        key_a = _fresh_key()
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": key_a})(),
        ):
            cipher = crypto.encrypt_token("secret")

        # Now rotate the key and try to decrypt.
        crypto._get_fernet.cache_clear()
        key_b = _fresh_key()
        assert key_a != key_b
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": key_b})(),
        ):
            with pytest.raises(
                crypto.MetaTokenCryptoError, match="failed to decrypt"
            ):
                crypto.decrypt_token(cipher)

    def test_empty_plaintext_rejected(self) -> None:
        key = _fresh_key()
        with patch.object(
            crypto, "get_settings",
            return_value=type("S", (), {"meta_token_encryption_key": key})(),
        ):
            with pytest.raises(ValueError):
                crypto.encrypt_token("")
            with pytest.raises(ValueError):
                crypto.decrypt_token("")
