"""Meta (Facebook) OAuth helpers for per-user ad-account connections.

Flow:

1. ``POST /api/me/meta/connect`` builds an authorization URL via
   :func:`build_meta_oauth_url` with a signed CSRF nonce as the
   ``state`` parameter. The frontend then redirects the browser there.
2. After the user approves, Meta redirects back to
   ``{meta_oauth_redirect_uri}?code=...&state=...``. The callback
   handler verifies ``state``, then calls
   :func:`exchange_code_for_token` to swap the short-lived code for a
   ~1-hour access token.
3. Because 1-hour tokens aren't useful for a daily cron,
   :func:`exchange_short_for_long_lived` immediately upgrades it to a
   ~60-day long-lived token.
4. :func:`fetch_meta_user_id` grabs the ``meta_user_id`` so the row is
   queryable by both app-user ID and Meta ID later.

The token is encrypted via :mod:`src.dashboard.crypto` before being
persisted in ``user_meta_connections``.

All Graph API calls use ``httpx`` with a 30-second timeout — the same
pattern as the rest of the async codebase.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from src.config import get_settings
from src.models.oauth import MetaAdAccountInfo, MetaPageInfo

logger = logging.getLogger(__name__)

_DIALOG_BASE = "https://www.facebook.com/{version}/dialog/oauth"
_TOKEN_BASE = "https://graph.facebook.com/{version}/oauth/access_token"
_ME_BASE = "https://graph.facebook.com/{version}/me"
_ME_ADACCOUNTS_BASE = "https://graph.facebook.com/{version}/me/adaccounts"
_ME_PAGES_BASE = "https://graph.facebook.com/{version}/me/accounts"

_HTTP_TIMEOUT_SECONDS = 30.0

# Hard cap on how many accounts / pages we persist on a single
# connection row. Agency users with access to hundreds of assets
# could otherwise blow up the JSONB column size and the import UI.
# 100 is arbitrary but well above the typical SMB case; users who hit
# the cap see an instructive truncation warning in logs and the UI.
_MAX_ENUMERATED_ITEMS = 100


@dataclass(frozen=True)
class MetaTokenResponse:
    """A parsed Meta token endpoint response.

    ``expires_at`` is computed at response time from ``expires_in`` (which
    is a relative "seconds from now") so callers can store an absolute
    timestamp. ``None`` when Meta returns a non-expiring token (rare).
    """

    access_token: str
    token_type: str
    expires_at: datetime | None


class MetaOAuthError(RuntimeError):
    """Raised on any failure in the OAuth exchange flow."""


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def build_meta_oauth_url(state: str) -> str:
    """Return the Facebook ``dialog/oauth`` URL for the initial redirect.

    ``state`` is an opaque nonce the caller generated (typically a
    signed HMAC of the user id + expiry). Meta echoes it back on the
    callback; we verify it there to block cross-site OAuth injections.
    """
    settings = get_settings()
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_oauth_redirect_uri,
        "state": state,
        "scope": settings.meta_oauth_scopes,
        "response_type": "code",
    }
    base = _DIALOG_BASE.format(version=settings.meta_graph_api_version)
    return f"{base}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def _parse_token_response(payload: dict) -> MetaTokenResponse:
    access_token = payload.get("access_token")
    if not access_token:
        raise MetaOAuthError(f"meta token response missing access_token: {payload!r}")
    token_type = payload.get("token_type", "bearer")
    expires_in = payload.get("expires_in")
    expires_at: datetime | None = None
    if isinstance(expires_in, int) and expires_in > 0:
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return MetaTokenResponse(
        access_token=access_token,
        token_type=token_type,
        expires_at=expires_at,
    )


async def exchange_code_for_token(code: str) -> MetaTokenResponse:
    """Swap a ``?code=`` for a short-lived (~1h) user access token.

    Called from the ``/api/auth/meta/callback`` endpoint immediately
    after verifying the ``state`` nonce. The returned token is *not*
    suitable for the daily cron — callers must upgrade it via
    :func:`exchange_short_for_long_lived`.
    """
    settings = get_settings()
    params = {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "redirect_uri": settings.meta_oauth_redirect_uri,
        "code": code,
    }
    url = _TOKEN_BASE.format(version=settings.meta_graph_api_version)

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise MetaOAuthError(f"meta code exchange request failed: {exc}") from exc

    if response.status_code != 200:
        raise MetaOAuthError(
            f"meta code exchange HTTP {response.status_code}: {response.text[:500]}"
        )
    return _parse_token_response(response.json())


async def exchange_short_for_long_lived(
    short_token: str,
) -> MetaTokenResponse:
    """Upgrade a ~1h short-lived token to a ~60d long-lived token.

    Per Meta docs: call the same ``oauth/access_token`` endpoint with
    ``grant_type=fb_exchange_token`` and pass the original short-lived
    token as ``fb_exchange_token``. Returns a new ``MetaTokenResponse``
    whose ``expires_at`` is roughly 60 days out.
    """
    settings = get_settings()
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "fb_exchange_token": short_token,
    }
    url = _TOKEN_BASE.format(version=settings.meta_graph_api_version)

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise MetaOAuthError(f"meta long-lived token exchange failed: {exc}") from exc

    if response.status_code != 200:
        raise MetaOAuthError(
            f"meta long-lived token HTTP {response.status_code}: {response.text[:500]}"
        )
    return _parse_token_response(response.json())


# ---------------------------------------------------------------------------
# Identity lookup
# ---------------------------------------------------------------------------


async def fetch_meta_user_id(access_token: str) -> str:
    """Return the Meta user ID for the given token.

    Used to populate ``user_meta_connections.meta_user_id`` so later
    debugging can cross-reference an app user with their Meta account
    without decrypting the token.
    """
    settings = get_settings()
    url = _ME_BASE.format(version=settings.meta_graph_api_version)
    params = {"fields": "id", "access_token": access_token}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise MetaOAuthError(f"meta /me request failed: {exc}") from exc

    if response.status_code != 200:
        raise MetaOAuthError(f"meta /me HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    meta_user_id = payload.get("id")
    if not meta_user_id:
        raise MetaOAuthError(f"meta /me response missing id: {payload!r}")
    return str(meta_user_id)


# ---------------------------------------------------------------------------
# Asset enumeration (Phase G)
# ---------------------------------------------------------------------------
#
# These two helpers run once at the end of the OAuth callback so the
# dashboard can show the user exactly which ad accounts and Pages their
# token can reach — without a second roundtrip on every pageload. The
# results are cached as JSONB on ``user_meta_connections`` and refreshed
# whenever the user re-OAuths.
#
# Both helpers are tolerant of empty responses — a brand-new Facebook
# account genuinely can have zero ad accounts or zero Pages, and the UX
# should show an actionable "create one in Meta Ads Manager first"
# message rather than erroring out. Malformed responses (missing
# required fields) raise ``MetaOAuthError`` so the callback can redirect
# to ``?meta_error=enumeration_failed``.


async def fetch_meta_ad_accounts(
    access_token: str,
) -> list[MetaAdAccountInfo]:
    """Return the ad accounts the token can reach.

    Calls ``GET /v18.0/me/adaccounts?fields=id,name,account_status,currency``
    via the same httpx pattern as :func:`fetch_meta_user_id`. Includes
    both directly-owned accounts and Business-Manager-delegated ones —
    Meta's response covers both transparently.

    Truncates at ``_MAX_ENUMERATED_ITEMS`` with a warning log so agency
    users with access to hundreds of accounts don't bloat the DB row.
    """
    settings = get_settings()
    url = _ME_ADACCOUNTS_BASE.format(version=settings.meta_graph_api_version)
    params = {
        "fields": "id,name,account_status,currency",
        "limit": str(_MAX_ENUMERATED_ITEMS),
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise MetaOAuthError(f"meta /me/adaccounts request failed: {exc}") from exc

    if response.status_code != 200:
        raise MetaOAuthError(
            f"meta /me/adaccounts HTTP {response.status_code}: {response.text[:500]}"
        )

    payload = response.json()
    raw_items = payload.get("data")
    if raw_items is None or not isinstance(raw_items, list):
        raise MetaOAuthError(f"meta /me/adaccounts missing data array: {payload!r}")

    accounts: list[MetaAdAccountInfo] = []
    for item in raw_items[:_MAX_ENUMERATED_ITEMS]:
        try:
            accounts.append(
                MetaAdAccountInfo(
                    id=str(item["id"]),
                    name=str(item.get("name") or "(unnamed account)"),
                    account_status=int(item.get("account_status") or 0),
                    currency=str(item.get("currency") or ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MetaOAuthError(f"meta /me/adaccounts malformed entry: {item!r} ({exc})") from exc

    if len(raw_items) > _MAX_ENUMERATED_ITEMS:
        logger.warning(
            "Truncated /me/adaccounts response from %d to %d entries",
            len(raw_items),
            _MAX_ENUMERATED_ITEMS,
        )

    return accounts


async def fetch_meta_pages(access_token: str) -> list[MetaPageInfo]:
    """Return the Facebook Pages the token can manage.

    Calls ``GET /v18.0/me/accounts?fields=id,name,category``. We do
    *not* request the per-Page ``access_token`` field that's also
    available here — our ad creation path uses the user-access token
    exclusively, so persisting Page tokens would only widen the blast
    radius of a DB leak. Revisit if/when organic Page publishing is
    added.
    """
    settings = get_settings()
    url = _ME_PAGES_BASE.format(version=settings.meta_graph_api_version)
    params = {
        "fields": "id,name,category",
        "limit": str(_MAX_ENUMERATED_ITEMS),
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise MetaOAuthError(f"meta /me/accounts request failed: {exc}") from exc

    if response.status_code != 200:
        raise MetaOAuthError(
            f"meta /me/accounts HTTP {response.status_code}: {response.text[:500]}"
        )

    payload = response.json()
    raw_items = payload.get("data")
    if raw_items is None or not isinstance(raw_items, list):
        raise MetaOAuthError(f"meta /me/accounts missing data array: {payload!r}")

    pages: list[MetaPageInfo] = []
    for item in raw_items[:_MAX_ENUMERATED_ITEMS]:
        try:
            pages.append(
                MetaPageInfo(
                    id=str(item["id"]),
                    name=str(item.get("name") or "(unnamed page)"),
                    category=str(item.get("category") or ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MetaOAuthError(f"meta /me/accounts malformed entry: {item!r} ({exc})") from exc

    if len(raw_items) > _MAX_ENUMERATED_ITEMS:
        logger.warning(
            "Truncated /me/accounts response from %d to %d entries",
            len(raw_items),
            _MAX_ENUMERATED_ITEMS,
        )

    return pages
