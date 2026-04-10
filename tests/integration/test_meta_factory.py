"""Integration tests for the per-user MetaAdapter factory.

The factory is the only supported path to a ``MetaAdapter`` after
Phase F. It must:

1. Build a real ``MetaAdapter`` from a valid stored connection.
2. Raise ``MetaConnectionMissing`` if the user never OAuthed.
3. Raise ``MetaTokenExpired`` if the stored expiry is in the past.
4. Raise ``MetaConnectionMissing`` for an un-owned campaign —
   there is no longer a global-token fallback. This is an
   operational anomaly (post-migration 008 every campaign is
   required to have an owner) so we surface it loudly instead of
   silently using a shared token.

The tests stub out the DB by monkeypatching the query helpers in
``src.adapters.meta_factory``. That keeps the factory wired to real
``decrypt_token`` + real ``MetaAdapter`` construction while staying
hermetic — no Postgres, no Fernet key churn (a one-shot key is
patched via ``get_settings``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from src.adapters.meta import MetaAdapter
from src.adapters.meta_factory import (
    get_meta_adapter_for_campaign,
    get_meta_adapter_for_user,
)
from src.dashboard import crypto
from src.exceptions import MetaConnectionMissing, MetaTokenExpired


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    """Every test gets a clean cached Fernet instance."""
    crypto._get_fernet.cache_clear()
    yield
    crypto._get_fernet.cache_clear()


def _stub_settings(key: str):
    """Build a stub settings object the factory + crypto can both read.

    ``meta_access_token`` was removed in Phase F — there is no
    global token anymore, so the stub deliberately omits it.
    """
    return SimpleNamespace(
        meta_token_encryption_key=key,
        meta_app_id="test-app-id",
        meta_app_secret="test-app-secret",
        meta_ad_account_id="act_1234567890",
        meta_page_id="111111111",
        meta_landing_page_url="https://example.com",
    )


class TestGetMetaAdapterForUser:
    async def test_valid_connection_returns_meta_adapter(self) -> None:
        """A stored, non-expired connection yields a MetaAdapter
        constructed with the decrypted token."""
        user_id = uuid4()
        key = Fernet.generate_key().decode()
        settings = _stub_settings(key)

        with patch.object(crypto, "get_settings", return_value=settings):
            encrypted = crypto.encrypt_token("user-long-lived-token")

        fake_connection = SimpleNamespace(
            user_id=user_id,
            meta_user_id="9876543210",
            encrypted_access_token=encrypted,
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            scopes=["ads_management", "ads_read"],
        )

        session = AsyncMock()
        with patch(
            "src.adapters.meta_factory.get_meta_connection",
            new=AsyncMock(return_value=fake_connection),
        ), patch(
            "src.adapters.meta_factory.get_settings", return_value=settings
        ), patch.object(
            crypto, "get_settings", return_value=settings
        ), patch(
            # Prevent the real facebook-business SDK from firing off a
            # network call during __init__.
            "src.adapters.meta.FacebookAdsApi.init"
        ):
            adapter = await get_meta_adapter_for_user(session, user_id)

        assert isinstance(adapter, MetaAdapter)
        # The adapter must have been constructed with the *decrypted*
        # user token, not the global one from settings.
        assert adapter._access_token == "user-long-lived-token"  # type: ignore[attr-defined]
        assert adapter._app_id == "test-app-id"  # type: ignore[attr-defined]

    async def test_missing_connection_raises(self) -> None:
        user_id = uuid4()
        session = AsyncMock()
        with patch(
            "src.adapters.meta_factory.get_meta_connection",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(MetaConnectionMissing, match="not connected"):
                await get_meta_adapter_for_user(session, user_id)

    async def test_expired_token_raises(self) -> None:
        user_id = uuid4()
        fake_connection = SimpleNamespace(
            user_id=user_id,
            meta_user_id="9876543210",
            encrypted_access_token="irrelevant",
            token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scopes=None,
        )
        session = AsyncMock()
        with patch(
            "src.adapters.meta_factory.get_meta_connection",
            new=AsyncMock(return_value=fake_connection),
        ):
            with pytest.raises(MetaTokenExpired, match="expired"):
                await get_meta_adapter_for_user(session, user_id)

    async def test_null_expiry_is_treated_as_non_expiring(self) -> None:
        """Some Meta tokens don't carry an expiry. The factory should
        not reject them — it should happily build an adapter."""
        user_id = uuid4()
        key = Fernet.generate_key().decode()
        settings = _stub_settings(key)

        with patch.object(crypto, "get_settings", return_value=settings):
            encrypted = crypto.encrypt_token("non-expiring-token")

        fake_connection = SimpleNamespace(
            user_id=user_id,
            meta_user_id="5555555555",
            encrypted_access_token=encrypted,
            token_expires_at=None,
            scopes=None,
        )
        session = AsyncMock()
        with patch(
            "src.adapters.meta_factory.get_meta_connection",
            new=AsyncMock(return_value=fake_connection),
        ), patch(
            "src.adapters.meta_factory.get_settings", return_value=settings
        ), patch.object(
            crypto, "get_settings", return_value=settings
        ), patch(
            "src.adapters.meta.FacebookAdsApi.init"
        ):
            adapter = await get_meta_adapter_for_user(session, user_id)

        assert adapter._access_token == "non-expiring-token"  # type: ignore[attr-defined]


class TestGetMetaAdapterForCampaign:
    async def test_owned_campaign_routes_to_user_factory(self) -> None:
        """A campaign with owner_user_id should resolve through the
        user's token, not the global fallback."""
        campaign_id = uuid4()
        owner_id = uuid4()
        key = Fernet.generate_key().decode()
        settings = _stub_settings(key)

        with patch.object(crypto, "get_settings", return_value=settings):
            encrypted = crypto.encrypt_token("owner-specific-token")

        fake_connection = SimpleNamespace(
            user_id=owner_id,
            meta_user_id="9876543210",
            encrypted_access_token=encrypted,
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            scopes=["ads_management"],
        )

        session = AsyncMock()
        with patch(
            "src.adapters.meta_factory.get_campaign_owner_id",
            new=AsyncMock(return_value=owner_id),
        ), patch(
            "src.adapters.meta_factory.get_meta_connection",
            new=AsyncMock(return_value=fake_connection),
        ), patch(
            "src.adapters.meta_factory.get_settings", return_value=settings
        ), patch.object(
            crypto, "get_settings", return_value=settings
        ), patch(
            "src.adapters.meta.FacebookAdsApi.init"
        ):
            adapter = await get_meta_adapter_for_campaign(session, campaign_id)

        assert adapter._access_token == "owner-specific-token"  # type: ignore[attr-defined]

    async def test_unowned_campaign_raises_missing_connection(self) -> None:
        """An un-owned campaign is a post-Phase-F anomaly.

        Every row in ``campaigns`` must have an ``owner_user_id``
        after migration 008. If one somehow doesn't (e.g., manual
        SQL drift or a new unscoped code path), the factory should
        surface it as ``MetaConnectionMissing`` so the orchestrator
        can skip the cycle cleanly rather than silently picking up
        a stale global token.
        """
        campaign_id = uuid4()

        session = AsyncMock()
        with patch(
            "src.adapters.meta_factory.get_campaign_owner_id",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(MetaConnectionMissing, match="no owner_user_id"):
                await get_meta_adapter_for_campaign(session, campaign_id)
