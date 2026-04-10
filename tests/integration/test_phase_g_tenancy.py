"""Phase G end-to-end tenancy test.

The single most load-bearing guarantee of Phase G is: **two different
users importing campaigns must never share ad account state**. The
pre-Phase-G system pulled ``settings.meta_ad_account_id`` for every
adapter regardless of which user owned the token, which meant user B's
"list my campaigns" call would silently point at user A's account.

This test files the guarantee away with a single scenario:

1. Two users each have their own ``user_meta_connections`` row with
   different ``available_ad_accounts`` JSONB payloads and different
   defaults.
2. User A imports a campaign picked from *A*'s ad account; user B
   imports a different campaign picked from *B*'s ad account.
3. Both ``campaigns`` rows must carry their respective users'
   account IDs on the new ``meta_ad_account_id`` column (not global
   settings, not each other's).
4. When the factory then resolves a MetaAdapter for each campaign,
   the returned adapter's ``_ad_account_id`` matches the owning
   user's pick — no cross-talk.
5. As a negative control, user B attempting to import with user A's
   ``ad_account_id`` fails closed with ``AdAccountNotAllowed`` — the
   cross-user injection guard the UI depends on.

The test is hermetic: no Postgres, no Meta SDK. Everything is mocked
at the module boundary. The point is to pin down the *wiring* — that
the per-campaign fields are written to and read from the right places
— not to re-test the individual helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from src.adapters.meta import MetaAdapter
from src.adapters.meta_factory import get_meta_adapter_for_campaign
from src.dashboard import crypto
from src.db.tables import (
    Campaign,
    Deployment,
    GenePoolEntry,
    Variant,
)
from src.exceptions import AdAccountNotAllowed
from src.services.campaign_import import import_campaign

# ---------------------------------------------------------------------------
# Fixtures — two users, two distinct Meta tenancies.
# ---------------------------------------------------------------------------


USER_A_ACCOUNT = "act_AAAAAAAAAA"
USER_A_PAGE = "page_aaaaaaaaaa"
USER_B_ACCOUNT = "act_BBBBBBBBBB"
USER_B_PAGE = "page_bbbbbbbbbb"


def _stub_settings(key: str):
    return SimpleNamespace(
        meta_token_encryption_key=key,
        meta_app_id="test-app-id",
        meta_app_secret="test-app-secret",
        max_campaigns_per_user=5,
        max_concurrent_variants=10,
        min_impressions=1000,
    )


def _connection_for(
    ad_account_id: str,
    page_id: str,
    encrypted_token: str,
) -> SimpleNamespace:
    """Build a ``user_meta_connections`` row stub pinned to one tenant."""
    return SimpleNamespace(
        meta_user_id="1234567890",
        encrypted_access_token=encrypted_token,
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
        scopes=["ads_management", "ads_read"],
        available_ad_accounts=[
            {
                "id": ad_account_id,
                "name": f"Account for {ad_account_id}",
                "account_status": 1,
                "currency": "USD",
            }
        ],
        available_pages=[
            {
                "id": page_id,
                "name": f"Page for {page_id}",
                "category": "Business",
            }
        ],
        default_ad_account_id=ad_account_id,
        default_page_id=page_id,
    )


def _fake_meta_campaigns_for(meta_campaign_id: str) -> list[dict]:
    return [
        {
            "meta_campaign_id": meta_campaign_id,
            "name": f"Campaign {meta_campaign_id}",
            "status": "ACTIVE",
            "daily_budget": 50.0,
            "created_time": None,
            "objective": "LINK_CLICKS",
        }
    ]


def _fake_campaign_ads() -> list[dict]:
    return [
        {
            "ad_id": "600000001",
            "ad_name": "ad_1",
            "status": "ACTIVE",
            "adset_id": "500000001",
            "creative_id": "c1",
            "creative_name": "creative_1",
            "headline": "Welcome",
            "body": "Try our product",
            "link_url": "https://example.com/a",
            "cta_type": "LEARN_MORE",
            "image_url": "https://img.example.com/1.jpg",
        }
    ]


def _campaign_row_result(
    owner_user_id,
    meta_ad_account_id: str,
    meta_page_id: str,
    landing_page_url: str,
) -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = (
        owner_user_id,
        meta_ad_account_id,
        meta_page_id,
        landing_page_url,
    )
    return result


# ---------------------------------------------------------------------------
# Support harness: an in-memory "session" that records what was
# ``session.add()``ed and assigns UUIDs on flush so downstream
# variants/deployments can reference the campaign id.
# ---------------------------------------------------------------------------


class _IterResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


def _make_session() -> tuple[AsyncMock, list]:
    added: list = []
    session = AsyncMock()

    def _add(obj):
        if isinstance(obj, Campaign) and obj.id is None:
            obj.id = uuid4()
        if isinstance(obj, Variant) and obj.id is None:
            obj.id = uuid4()
        added.append(obj)

    session.add = _add
    session.flush = AsyncMock()
    # Gene pool existence check returns empty → everything is "new".
    session.execute = AsyncMock(return_value=_IterResult([]))
    return session, added


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    crypto._get_fernet.cache_clear()
    yield
    crypto._get_fernet.cache_clear()


class TestTwoUserTenancyIsolation:
    async def test_two_users_import_into_their_own_accounts(self) -> None:
        """Two users, two tenancies, zero cross-talk.

        User A imports campaign ``meta_aaa_001`` picked from account
        ``USER_A_ACCOUNT``; user B imports ``meta_bbb_001`` from
        ``USER_B_ACCOUNT``. Both Campaign rows must end up with the
        correct per-campaign tenancy columns.
        """
        user_a_id = uuid4()
        user_b_id = uuid4()
        key = Fernet.generate_key().decode()
        settings = _stub_settings(key)

        with patch.object(crypto, "get_settings", return_value=settings):
            token_a = crypto.encrypt_token("user-a-token")
            token_b = crypto.encrypt_token("user-b-token")

        connection_a = _connection_for(USER_A_ACCOUNT, USER_A_PAGE, token_a)
        connection_b = _connection_for(USER_B_ACCOUNT, USER_B_PAGE, token_b)

        # Per-user adapter stubs that only know about their own campaigns.
        adapter_a = SimpleNamespace(
            list_campaigns=AsyncMock(return_value=_fake_meta_campaigns_for("meta_aaa_001")),
            list_campaign_ads=AsyncMock(return_value=_fake_campaign_ads()),
        )
        adapter_b = SimpleNamespace(
            list_campaigns=AsyncMock(return_value=_fake_meta_campaigns_for("meta_bbb_001")),
            list_campaign_ads=AsyncMock(return_value=_fake_campaign_ads()),
        )

        # The session and the connection/adapter mocks flip based on
        # which user we're operating on. We drive two imports in
        # sequence and assert each lands on its own tenant.
        session_a, added_a = _make_session()
        session_b, added_b = _make_session()

        with (
            patch("src.services.campaign_import.get_settings", return_value=settings),
            patch(
                "src.services.campaign_import.count_active_campaigns_for_user",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "src.services.campaign_import.get_meta_connection",
                new=AsyncMock(return_value=connection_a),
            ),
            patch(
                "src.services.campaign_import._build_user_adapter",
                new=AsyncMock(return_value=adapter_a),
            ),
        ):
            await import_campaign(
                session_a,
                user_a_id,
                meta_campaign_id="meta_aaa_001",
                ad_account_id=USER_A_ACCOUNT,
                page_id=USER_A_PAGE,
                landing_page_url="https://a.example.com",
            )

        with (
            patch("src.services.campaign_import.get_settings", return_value=settings),
            patch(
                "src.services.campaign_import.count_active_campaigns_for_user",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "src.services.campaign_import.get_meta_connection",
                new=AsyncMock(return_value=connection_b),
            ),
            patch(
                "src.services.campaign_import._build_user_adapter",
                new=AsyncMock(return_value=adapter_b),
            ),
        ):
            await import_campaign(
                session_b,
                user_b_id,
                meta_campaign_id="meta_bbb_001",
                ad_account_id=USER_B_ACCOUNT,
                page_id=USER_B_PAGE,
                landing_page_url="https://b.example.com",
            )

        campaign_a = next(c for c in added_a if isinstance(c, Campaign))
        campaign_b = next(c for c in added_b if isinstance(c, Campaign))

        # Isolation invariants:
        assert campaign_a.owner_user_id == user_a_id
        assert campaign_a.meta_ad_account_id == USER_A_ACCOUNT
        assert campaign_a.meta_page_id == USER_A_PAGE
        assert campaign_a.landing_page_url == "https://a.example.com"

        assert campaign_b.owner_user_id == user_b_id
        assert campaign_b.meta_ad_account_id == USER_B_ACCOUNT
        assert campaign_b.meta_page_id == USER_B_PAGE
        assert campaign_b.landing_page_url == "https://b.example.com"

        # And the columns are not equal to each other — explicit.
        assert campaign_a.meta_ad_account_id != campaign_b.meta_ad_account_id
        assert campaign_a.meta_page_id != campaign_b.meta_page_id

    async def test_factory_reads_per_campaign_columns_not_settings(self) -> None:
        """Round-tripping through the factory: a campaign row whose
        ``meta_ad_account_id`` is user B's value must yield a
        ``MetaAdapter`` scoped to user B's account, *not* any global
        fallback.
        """
        campaign_id = uuid4()
        owner_id = uuid4()
        key = Fernet.generate_key().decode()
        settings = _stub_settings(key)

        with patch.object(crypto, "get_settings", return_value=settings):
            encrypted = crypto.encrypt_token("user-b-token")

        fake_connection = SimpleNamespace(
            user_id=owner_id,
            meta_user_id="1234567890",
            encrypted_access_token=encrypted,
            token_expires_at=datetime.now(UTC) + timedelta(days=30),
            scopes=["ads_management"],
        )

        session = AsyncMock()
        session.execute.return_value = _campaign_row_result(
            owner_user_id=owner_id,
            meta_ad_account_id=USER_B_ACCOUNT,
            meta_page_id=USER_B_PAGE,
            landing_page_url="https://b.example.com",
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

        assert isinstance(adapter, MetaAdapter)
        # The adapter is locked to user B's tenancy — no global bleed.
        assert adapter._ad_account_id == USER_B_ACCOUNT  # type: ignore[attr-defined]
        assert adapter._page_id == USER_B_PAGE  # type: ignore[attr-defined]
        assert adapter._landing_page_url == "https://b.example.com"  # type: ignore[attr-defined]
        assert adapter._access_token == "user-b-token"  # type: ignore[attr-defined]

    async def test_user_b_cannot_import_with_user_a_ad_account(self) -> None:
        """Negative control: the cross-user allowlist guard.

        User B's connection only enumerates their own account. Even
        if B somehow learns A's account ID, posting it as
        ``ad_account_id`` to the import endpoint must be rejected
        before any Meta I/O happens.
        """
        user_b_id = uuid4()
        key = Fernet.generate_key().decode()
        settings = _stub_settings(key)

        with patch.object(crypto, "get_settings", return_value=settings):
            token_b = crypto.encrypt_token("user-b-token")

        connection_b = _connection_for(USER_B_ACCOUNT, USER_B_PAGE, token_b)

        session = AsyncMock()
        session.flush = AsyncMock()
        build_adapter = AsyncMock()

        with (
            patch("src.services.campaign_import.get_settings", return_value=settings),
            patch(
                "src.services.campaign_import.count_active_campaigns_for_user",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "src.services.campaign_import.get_meta_connection",
                new=AsyncMock(return_value=connection_b),
            ),
            patch(
                "src.services.campaign_import._build_user_adapter",
                new=build_adapter,
            ),
            pytest.raises(AdAccountNotAllowed),
        ):
            await import_campaign(
                session,
                user_b_id,
                meta_campaign_id="meta_aaa_001",
                ad_account_id=USER_A_ACCOUNT,  # the forbidden id
                page_id=USER_B_PAGE,
            )

        # Critically: the adapter was never built — no Meta call
        # would have been issued with the stolen account id.
        build_adapter.assert_not_awaited()


# Silence linters about unused imports in strict modes.
_ = Deployment
_ = GenePoolEntry
