"""Integration tests for the per-user MetaAdapter factory.

The factory is the only supported path to a ``MetaAdapter`` after
Phase F, and Phase G took the next step: per-campaign ad account +
Page + landing-page URL. It must:

1. Build a real ``MetaAdapter`` from a valid stored connection, given
   explicit per-campaign ``ad_account_id`` / ``page_id`` /
   ``landing_page_url`` values (no more global settings fallback).
2. Raise ``MetaConnectionMissing`` if the user never OAuthed.
3. Raise ``MetaTokenExpired`` if the stored expiry is in the past.
4. Raise ``MetaConnectionMissing`` for an un-owned campaign or a
   campaign whose ``meta_ad_account_id`` / ``meta_page_id`` columns
   are NULL — both are operational anomalies (migration 008 pins an
   owner on every row, migration 009 enforces the tenancy columns
   via a partial CHECK) that we surface loudly instead of silently
   using a shared token.

The tests stub out the DB by monkeypatching the query helpers in
``src.adapters.meta_factory`` (and, for ``get_meta_adapter_for_campaign``,
by stubbing ``session.execute`` to return a fake row matching the SQL
select on ``Campaign`` columns). That keeps the factory wired to real
``decrypt_token`` + real ``MetaAdapter`` construction while staying
hermetic — no Postgres, no Fernet key churn (a one-shot key is
patched via ``get_settings``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
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

    ``meta_access_token`` was removed in Phase F and
    ``meta_ad_account_id`` / ``meta_page_id`` / ``meta_landing_page_url``
    in Phase G — the stub deliberately omits all of them to make sure
    no test path depends on global-settings fallbacks that no longer
    exist.
    """
    return SimpleNamespace(
        meta_token_encryption_key=key,
        meta_app_id="test-app-id",
        meta_app_secret="test-app-secret",
    )


def _campaign_row_result(
    owner_user_id,
    meta_ad_account_id: str | None,
    meta_page_id: str | None,
    landing_page_url: str | None,
) -> MagicMock:
    """Fake ``Result`` object with a ``.one_or_none()`` returning our row.

    ``get_meta_adapter_for_campaign`` issues ``await session.execute(stmt)``
    and then calls ``.one_or_none()`` on the result. Since
    ``session`` is an ``AsyncMock``, we attach a plain ``MagicMock``
    as the execute return value so the .one_or_none() call works
    without needing to await anything.
    """
    result = MagicMock()
    result.one_or_none.return_value = (
        owner_user_id,
        meta_ad_account_id,
        meta_page_id,
        landing_page_url,
    )
    return result


def _missing_campaign_row_result() -> MagicMock:
    """Fake ``Result`` for the no-such-campaign case."""
    result = MagicMock()
    result.one_or_none.return_value = None
    return result


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
            token_expires_at=datetime.now(UTC) + timedelta(days=30),
            scopes=["ads_management", "ads_read"],
        )

        session = AsyncMock()
        with (
            patch(
                "src.adapters.meta_factory.get_meta_connection",
                new=AsyncMock(return_value=fake_connection),
            ),
            patch("src.adapters.meta_factory.get_settings", return_value=settings),
            patch.object(crypto, "get_settings", return_value=settings),
            patch(
                # Prevent the real facebook-business SDK from firing off a
                # network call during __init__.
                "src.adapters.meta.FacebookAdsApi.init"
            ),
        ):
            adapter = await get_meta_adapter_for_user(
                session,
                user_id,
                ad_account_id="act_1234567890",
                page_id="111111111",
                landing_page_url="https://example.com",
            )

        assert isinstance(adapter, MetaAdapter)
        # The adapter must have been constructed with the *decrypted*
        # user token, not the global one from settings.
        assert adapter._access_token == "user-long-lived-token"  # type: ignore[attr-defined]
        assert adapter._app_id == "test-app-id"  # type: ignore[attr-defined]
        # Per-campaign values flowed through, not anything global.
        assert adapter._ad_account_id == "act_1234567890"  # type: ignore[attr-defined]
        assert adapter._page_id == "111111111"  # type: ignore[attr-defined]

    async def test_missing_connection_raises(self) -> None:
        user_id = uuid4()
        session = AsyncMock()
        with (
            patch(
                "src.adapters.meta_factory.get_meta_connection",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(MetaConnectionMissing, match="not connected"),
        ):
            await get_meta_adapter_for_user(
                session,
                user_id,
                ad_account_id="act_1234567890",
                page_id="111111111",
                landing_page_url="https://example.com",
            )

    async def test_expired_token_raises(self) -> None:
        user_id = uuid4()
        fake_connection = SimpleNamespace(
            user_id=user_id,
            meta_user_id="9876543210",
            encrypted_access_token="irrelevant",
            token_expires_at=datetime.now(UTC) - timedelta(hours=1),
            scopes=None,
        )
        session = AsyncMock()
        with (
            patch(
                "src.adapters.meta_factory.get_meta_connection",
                new=AsyncMock(return_value=fake_connection),
            ),
            pytest.raises(MetaTokenExpired, match="expired"),
        ):
            await get_meta_adapter_for_user(
                session,
                user_id,
                ad_account_id="act_1234567890",
                page_id="111111111",
                landing_page_url="https://example.com",
            )

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
        with (
            patch(
                "src.adapters.meta_factory.get_meta_connection",
                new=AsyncMock(return_value=fake_connection),
            ),
            patch("src.adapters.meta_factory.get_settings", return_value=settings),
            patch.object(crypto, "get_settings", return_value=settings),
            patch("src.adapters.meta.FacebookAdsApi.init"),
        ):
            adapter = await get_meta_adapter_for_user(
                session,
                user_id,
                ad_account_id="act_1234567890",
                page_id="111111111",
                landing_page_url="https://example.com",
            )

        assert adapter._access_token == "non-expiring-token"  # type: ignore[attr-defined]


class TestGetMetaAdapterForCampaign:
    async def test_owned_campaign_routes_to_user_factory(self) -> None:
        """A campaign with owner + tenancy columns resolves through the
        user's token and per-campaign account/page, not any global
        fallback."""
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
            token_expires_at=datetime.now(UTC) + timedelta(days=30),
            scopes=["ads_management"],
        )

        session = AsyncMock()
        session.execute.return_value = _campaign_row_result(
            owner_user_id=owner_id,
            meta_ad_account_id="act_9999999999",
            meta_page_id="222222222",
            landing_page_url="https://owner.example.com",
        )
        with (
            patch(
                "src.adapters.meta_factory.get_meta_connection",
                new=AsyncMock(return_value=fake_connection),
            ),
            patch("src.adapters.meta_factory.get_settings", return_value=settings),
            patch.object(crypto, "get_settings", return_value=settings),
            patch("src.adapters.meta.FacebookAdsApi.init"),
        ):
            adapter = await get_meta_adapter_for_campaign(session, campaign_id)

        assert adapter._access_token == "owner-specific-token"  # type: ignore[attr-defined]
        # The per-campaign tenancy columns flowed through to the adapter,
        # not anything pulled from global settings.
        assert adapter._ad_account_id == "act_9999999999"  # type: ignore[attr-defined]
        assert adapter._page_id == "222222222"  # type: ignore[attr-defined]
        assert adapter._landing_page_url == "https://owner.example.com"  # type: ignore[attr-defined]

    async def test_nonexistent_campaign_raises_missing_connection(self) -> None:
        """A campaign_id that matches no row is a data anomaly we
        surface instead of silently proceeding."""
        campaign_id = uuid4()

        session = AsyncMock()
        session.execute.return_value = _missing_campaign_row_result()

        with pytest.raises(MetaConnectionMissing, match="does not exist"):
            await get_meta_adapter_for_campaign(session, campaign_id)

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
        session.execute.return_value = _campaign_row_result(
            owner_user_id=None,
            meta_ad_account_id="act_1234567890",
            meta_page_id="111111111",
            landing_page_url="https://example.com",
        )

        with pytest.raises(MetaConnectionMissing, match="no owner_user_id"):
            await get_meta_adapter_for_campaign(session, campaign_id)

    async def test_missing_tenancy_columns_raise_missing_connection(self) -> None:
        """Phase G invariant: Meta campaigns must carry
        ``meta_ad_account_id`` + ``meta_page_id``.

        The partial CHECK constraint in migration 009 enforces this
        at the DB layer for ``platform = 'meta'`` rows, but the
        factory has its own guard so a code path that somehow
        constructs a Python-side ``Campaign`` without the columns
        still fails loudly rather than silently building an adapter
        pointed at an empty account ID.
        """
        campaign_id = uuid4()
        owner_id = uuid4()

        session = AsyncMock()
        session.execute.return_value = _campaign_row_result(
            owner_user_id=owner_id,
            meta_ad_account_id=None,  # the Phase G invariant violation
            meta_page_id="111111111",
            landing_page_url="https://example.com",
        )

        with pytest.raises(
            MetaConnectionMissing,
            match="missing meta_ad_account_id or meta_page_id",
        ):
            await get_meta_adapter_for_campaign(session, campaign_id)
