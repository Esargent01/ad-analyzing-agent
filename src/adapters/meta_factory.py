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
  has no ``owner_user_id`` — a state that should be impossible
  after the Phase F migration).
- :class:`~src.exceptions.MetaTokenExpired` — the long-lived token's
  60-day clock ran out.

Phase F removed the legacy global-token fallback. Every campaign
now has a non-null ``owner_user_id`` (enforced by migration 008),
and every adapter is constructed from that owner's decrypted
OAuth token.

.. note::

   ``meta_ad_account_id``, ``meta_page_id``, and
   ``meta_landing_page_url`` are still read from global settings as
   a pragmatic stopgap — the import flow (Phase D) does not yet
   capture these per-campaign. A future "Phase G" will move those
   into ``campaigns`` columns so different campaigns can target
   different ad accounts and landing pages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.meta import MetaAdapter
from src.config import get_settings
from src.dashboard.crypto import decrypt_token
from src.db.queries import get_campaign_owner_id, get_meta_connection
from src.exceptions import MetaConnectionMissing, MetaTokenExpired

logger = logging.getLogger(__name__)


async def get_meta_adapter_for_user(
    session: AsyncSession, user_id: UUID
) -> MetaAdapter:
    """Fetch the user's stored connection and build a fresh adapter.

    Raises:
        MetaConnectionMissing: no row in ``user_meta_connections``.
        MetaTokenExpired: the stored long-lived token is past its
            ``token_expires_at`` timestamp.
    """
    connection = await get_meta_connection(session, user_id)
    if connection is None:
        raise MetaConnectionMissing(
            f"User {user_id} has not connected a Meta account."
        )

    # Token expiry is stored when the long-lived exchange runs. If
    # the value is NULL we assume it's non-expiring (some Meta token
    # flavours don't have an expiry) and skip the check.
    if connection.token_expires_at is not None:
        now = datetime.now(timezone.utc)
        if connection.token_expires_at <= now:
            raise MetaTokenExpired(
                f"User {user_id}'s Meta token expired at "
                f"{connection.token_expires_at.isoformat()} — "
                "they need to reconnect."
            )

    plaintext_token = decrypt_token(connection.encrypted_access_token)

    settings = get_settings()
    # Phase C intentionally still uses the global ad_account_id /
    # page_id / landing_page_url — those become per-user in Phase D
    # when the import flow records which of the user's Meta ad
    # accounts a given campaign lives under.
    return MetaAdapter(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        access_token=plaintext_token,
        ad_account_id=settings.meta_ad_account_id,
        page_id=settings.meta_page_id,
        landing_page_url=settings.meta_landing_page_url,
    )


async def get_meta_adapter_for_campaign(
    session: AsyncSession, campaign_id: UUID
) -> MetaAdapter:
    """Resolve the campaign's owner and hand back their adapter.

    Every campaign is required to have an ``owner_user_id`` after
    the Phase F migration (008). If we somehow encounter a row
    without one — an operational anomaly, not an expected state —
    we raise ``MetaConnectionMissing`` rather than silently using
    a stale global token.

    Raises:
        MetaConnectionMissing: campaign has no owner, or the owner
            has not connected a Meta account.
        MetaTokenExpired: the owner's stored token has expired.
    """
    owner_user_id = await get_campaign_owner_id(session, campaign_id)
    if owner_user_id is None:
        raise MetaConnectionMissing(
            f"Campaign {campaign_id} has no owner_user_id — data anomaly. "
            "Every campaign must be assigned to a user after the Phase F "
            "migration; investigate before retrying."
        )
    return await get_meta_adapter_for_user(session, owner_user_id)
