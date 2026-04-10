"""Pydantic models for Meta OAuth enumeration payloads (Phase G).

These describe the *connection-scoped* data we cache on
``user_meta_connections`` after an OAuth callback: the list of ad
accounts and Pages the user's long-lived token can reach. They live
in their own module (rather than piggy-backing on
``src.models.campaigns``) because they're tied to the connection, not
to any particular campaign — and because keeping them separate avoids
a cyclic import between the dashboard OAuth helpers and the campaign
import service.

Both models are written to JSONB columns via
``src.db.queries.upsert_meta_connection``, so the field names must
match the JSON we actually serialise. Don't rename fields lightly —
a schema drift will silently corrupt existing rows.

The fetch helpers in ``src.dashboard.meta_oauth`` build these from
raw Graph API dicts. The dashboard endpoints in ``src.dashboard.app``
surface them on ``GET /api/me/meta/status`` and
``GET /api/me/meta/campaigns`` so the frontend can render account +
Page dropdowns without a second roundtrip.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MetaAdAccountInfo(BaseModel):
    """One ad account returned by ``GET /me/adaccounts``.

    Meta returns ``account_status`` as an integer (1 = ACTIVE,
    2 = DISABLED, 3 = UNSETTLED, ...). We keep the raw integer on
    the wire so the frontend can display "Disabled" badges without
    the backend having to track every status the Graph API adds.

    ``id`` is the ``act_123456`` form (with the ``act_`` prefix) —
    that's what downstream adapter calls need to scope queries.
    """

    model_config = ConfigDict(strict=True)

    id: str
    name: str
    account_status: int
    currency: str


class MetaPageInfo(BaseModel):
    """One Facebook Page returned by ``GET /me/accounts``.

    We deliberately do **not** persist the per-Page ``access_token``
    that ``/me/accounts`` also returns. Ad creation uses the
    user-access token, not a Page token, so the Page token is
    unnecessary for our current scope and leaving it out narrows the
    blast radius if a DB row ever leaks.

    If a future phase adds organic Page publishing (posts alongside
    ads), revisit — at that point the Page token becomes load-bearing
    and must be encrypted alongside the user token.
    """

    model_config = ConfigDict(strict=True)

    id: str
    name: str
    category: str
