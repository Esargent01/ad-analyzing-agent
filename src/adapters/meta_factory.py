"""Per-user MetaAdapter factory.

The pre-Phase-C world had a single global ``META_ACCESS_TOKEN`` in
settings that every ``MetaAdapter`` instance shared. That couldn't
scale: we need every user's campaigns to run on *their* Meta token so
we respect their ad account boundaries and honour per-user rate limits.

This module is the bridge. Instead of constructing a ``MetaAdapter``
directly from settings, callers now ask for one by user ID or by
campaign ID; the factory decrypts the stored token on the fly and
hands back a fresh adapter. Adapters are intentionally short-lived —
construct one at the start of a cycle, discard at the end. Never
cache.

Two failure modes are surfaced as exceptions so the orchestrator can
skip an affected cycle without dragging the whole batch down:

- :class:`~src.exceptions.MetaConnectionMissing` — the user never
  clicked "Connect Meta", or disconnected since (or the campaign
  has no per-campaign ``meta_ad_account_id`` / ``meta_page_id`` set,
  which should be impossible after the Phase G migration).
- :class:`~src.exceptions.MetaTokenExpired` — the long-lived token's
  60-day clock ran out.

Phase G removed the last remnants of the global-settings stopgap.
``get_meta_adapter_for_user`` now requires explicit per-campaign
``ad_account_id`` / ``page_id`` / ``landing_page_url`` arguments,
and ``get_meta_adapter_for_campaign`` reads those values off the
``campaigns`` row before delegating. Global
``settings.meta_ad_account_id`` / ``meta_page_id`` /
``meta_landing_page_url`` no longer exist.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.meta import MetaAdapter
from src.config import get_settings
from src.dashboard.crypto import decrypt_token
from src.db.queries import get_meta_connection
from src.db.tables import Campaign
from src.exceptions import MetaConnectionMissing, MetaTokenExpired

logger = logging.getLogger(__name__)


async def get_meta_adapter_for_user(
    session: AsyncSession,
    user_id: UUID,
    ad_account_id: str,
    page_id: str,
    landing_page_url: str | None = None,
) -> MetaAdapter:
    """Fetch the user's stored connection and build a fresh adapter.

    Phase G made ``ad_account_id`` and ``page_id`` required — global
    settings no longer supply them. Callers are responsible for
    resolving the account / Page from either the ``campaigns`` row
    (via :func:`get_meta_adapter_for_campaign`) or from the user's
    picked values during the import flow.

    Raises:
        MetaConnectionMissing: no row in ``user_meta_connections``.
        MetaTokenExpired: the stored long-lived token is past its
            ``token_expires_at`` timestamp.
    """
    connection = await get_meta_connection(session, user_id)
    if connection is None:
        raise MetaConnectionMissing(f"User {user_id} has not connected a Meta account.")

    # Token expiry is stored when the long-lived exchange runs. If
    # the value is NULL we assume it's non-expiring (some Meta token
    # flavours don't have an expiry) and skip the check.
    if connection.token_expires_at is not None:
        now = datetime.now(UTC)
        if connection.token_expires_at <= now:
            raise MetaTokenExpired(
                f"User {user_id}'s Meta token expired at "
                f"{connection.token_expires_at.isoformat()} — "
                "they need to reconnect."
            )

    plaintext_token = decrypt_token(connection.encrypted_access_token)

    settings = get_settings()
    return MetaAdapter(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        access_token=plaintext_token,
        ad_account_id=ad_account_id,
        page_id=page_id,
        landing_page_url=landing_page_url or "",
    )


async def get_meta_adapter_for_campaign(session: AsyncSession, campaign_id: UUID) -> MetaAdapter:
    """Resolve the campaign's owner + tenancy columns and hand back an adapter.

    After Phase G every Meta campaign row carries its own
    ``meta_ad_account_id`` / ``meta_page_id`` / ``landing_page_url``.
    A NULL on either of the required columns is a data anomaly — the
    Phase G migration enforces NOT NULL for ``platform = 'meta'`` rows
    via a partial CHECK constraint, and the import flow always writes
    both. If we somehow encounter a row without them, raise
    ``MetaConnectionMissing`` rather than silently falling back to
    anything.

    Raises:
        MetaConnectionMissing: campaign has no owner, is missing the
            per-campaign tenancy columns, or the owner has not
            connected a Meta account.
        MetaTokenExpired: the owner's stored token has expired.
    """
    stmt = select(
        Campaign.owner_user_id,
        Campaign.meta_ad_account_id,
        Campaign.meta_page_id,
        Campaign.landing_page_url,
    ).where(Campaign.id == campaign_id)
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise MetaConnectionMissing(f"Campaign {campaign_id} does not exist.")

    owner_user_id, account_id, page_id, landing_page_url = row

    if owner_user_id is None:
        raise MetaConnectionMissing(
            f"Campaign {campaign_id} has no owner_user_id — data anomaly. "
            "Every campaign must be assigned to a user after the Phase F "
            "migration; investigate before retrying."
        )
    if not account_id or not page_id:
        raise MetaConnectionMissing(
            f"Campaign {campaign_id} is missing meta_ad_account_id or "
            "meta_page_id — run migration 009 and re-import if needed."
        )

    return await get_meta_adapter_for_user(
        session,
        owner_user_id,
        ad_account_id=account_id,
        page_id=page_id,
        landing_page_url=landing_page_url,
    )
