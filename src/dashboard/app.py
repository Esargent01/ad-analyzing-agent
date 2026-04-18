"""Dashboard FastAPI app: legacy read-only views + Phase 2 auth'd JSON API.

This module has two overlapping surfaces:

1. **Legacy surface** — Jinja2-rendered HTML pages and the tokenized
   ``/review/{token}`` flow used by the weekly review email. These are
   unauthenticated (token-verified) and stay untouched so existing
   customers keep working.

2. **Phase 2 API** — cookie-authenticated JSON endpoints under
   ``/api/*`` that the React dashboard (``frontend/``) consumes. Session
   cookies are HttpOnly + Secure + SameSite=None; mutating requests also
   require a matching ``X-CSRF-Token`` header (double-submit cookie).

Dashboard queries use ``noload()`` to prevent eager loading of heavy
relationship chains (Campaign → Variant → Metric) that the dashboard
doesn't need.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from src.config import get_settings
from src.dashboard.auth import (
    create_magic_link_token,
    create_oauth_state_token,
    create_session_token,
    generate_csrf_token,
    hash_magic_link_token,
    verify_magic_link_token,
    verify_oauth_state_token,
)
from src.dashboard.crypto import MetaTokenCryptoError, encrypt_token
from src.dashboard.deps import (
    get_current_user,
    get_db_session,
    require_campaign_access,
    require_csrf,
)
from src.dashboard.meta_oauth import (
    MetaOAuthError,
    build_meta_oauth_url,
    exchange_code_for_token,
    exchange_short_for_long_lived,
    fetch_meta_ad_accounts,
    fetch_meta_pages,
    fetch_meta_user_id,
)
from src.dashboard.tokens import verify_review_token
from src.db.engine import get_session
from src.db.queries import (
    add_gene_pool_entry,
    approve_proposal,
    approve_variant,
    consume_magic_link_token,
    count_active_campaigns_for_user,
    create_data_deletion_request,
    create_user,
    delete_meta_connection,
    delete_meta_connection_by_meta_user_id,
    get_data_deletion_request,
    get_element_rankings,
    get_meta_connection,
    get_pending_approvals,
    get_recent_cycles,
    get_top_interactions,
    get_user_by_email,
    get_user_campaigns,
    list_gene_pool_entries,
    reject_proposal,
    reject_variant,
    touch_last_login,
    upsert_meta_connection,
)
from src.db.tables import Campaign, User, Variant
from src.exceptions import (
    AdAccountNotAllowed,
    CampaignAlreadyImported,
    CampaignCapExceeded,
    MetaConnectionMissing,
    MetaTokenExpired,
    MultipleAdAccountsNoDefault,
)
from src.models.approvals import PendingApproval
from src.models.campaigns import (
    CampaignImportFailure,
    CampaignImportRequest,
    CampaignImportResult,
    ImportableCampaignsResponse,
)
from src.models.oauth import MetaAdAccountInfo, MetaPageInfo
from src.models.reports import DailyReport, ProposedVariant, WeeklyReport
from src.reports.auth_email import send_magic_link
from src.services.approval_executor import execute_approved_action
from src.services.campaign_import import (
    import_campaign,
    list_importable_campaigns,
)
from src.services.reports import build_daily_report, build_weekly_report
from src.services.weekly import load_pending_approvals, load_proposed_variants

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app = FastAPI(
    title="Kleiber Dashboard",
    description="Read-only monitoring dashboard + authenticated JSON API",
    docs_url=None,
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
#
# Two layers for ``POST /api/auth/magic-link``:
#
# 1. **Per-IP** — slowapi decorator with a 20/hour budget. Keyed by the
#    left-most entry in ``X-Forwarded-For`` so we get the real client IP
#    behind Fly.io / Vercel edge proxies instead of the proxy's own IP.
# 2. **Per-email** — a small in-process sliding window implemented in
#    ``_email_bucket`` below, 5/minute. slowapi's decorator key function
#    can't see the request body (the body hasn't been parsed at that
#    point), so per-email limiting is done manually inside the handler.
#
# Both are best-effort: the process-local in-memory store is fine for a
# single-node deploy and keeps us off Redis for Phase A. When we scale
# out, move both limits to a shared backend.


def _forwarded_ip_key(request: Request) -> str:
    """Return the real client IP, honouring ``X-Forwarded-For``.

    Fly.io / Vercel sit in front of the backend, so ``request.client.host``
    is the proxy IP, not the user's. Fall back to ``get_remote_address``
    when no forwarded header is present.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_forwarded_ip_key)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limited", "detail": str(exc.detail)},
    )


# Per-email sliding window: {email: [timestamp, timestamp, ...]}
_MAGIC_LINK_EMAIL_WINDOW_SECONDS = 60
_MAGIC_LINK_EMAIL_MAX_HITS = 5
_email_bucket: dict[str, list[float]] = {}


def _check_email_rate_limit(email: str) -> bool:
    """Record a hit for ``email`` and return True if the limit is exceeded.

    Allows up to ``_MAGIC_LINK_EMAIL_MAX_HITS`` requests per
    ``_MAGIC_LINK_EMAIL_WINDOW_SECONDS`` per email. Old timestamps are
    pruned on each call so the dict stays bounded over time.
    """
    import time

    now = time.monotonic()
    cutoff = now - _MAGIC_LINK_EMAIL_WINDOW_SECONDS
    hits = [t for t in _email_bucket.get(email, []) if t > cutoff]
    hits.append(now)
    _email_bucket[email] = hits
    return len(hits) > _MAGIC_LINK_EMAIL_MAX_HITS


# ---------------------------------------------------------------------------
# CORS — only allow configured frontend origins
# ---------------------------------------------------------------------------


def _configured_origins() -> list[str]:
    settings = get_settings()
    return [o.strip() for o in settings.frontend_origins.split(",") if o.strip()]


_cors_origins = _configured_origins()
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )


# ---------------------------------------------------------------------------
# Health check — used by Fly.io HTTP health checks and uptime monitors.
# Intentionally does NOT touch the database so a degraded DB doesn't take
# the whole process out of rotation (and so a cold-started machine can
# pass its first health check before the DB pool warms up).
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Lightweight dashboard queries (avoid eager-loading metrics)
# ---------------------------------------------------------------------------


async def _get_campaigns_light(session):
    """Load campaigns without eager-loading variants/metrics."""
    stmt = select(Campaign).where(Campaign.is_active.is_(True)).options(noload("*"))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_campaign_light(session, campaign_id: UUID):
    """Load a single campaign without eager-loading relationships."""
    stmt = select(Campaign).where(Campaign.id == campaign_id).options(noload("*"))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_variants_light(session, campaign_id: UUID):
    """Load variants without eager-loading metrics."""
    stmt = (
        select(Variant)
        .where(Variant.campaign_id == campaign_id)
        .options(noload("*"))
        .order_by(Variant.variant_code)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> Any:
    """Convert ORM objects to JSON-safe dicts."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if hasattr(obj, "__dict__"):
        result = {}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            result[k] = _serialize(v)
        return result
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request) -> HTMLResponse:
    """Main dashboard page."""
    async with get_session() as session:
        campaigns = await _get_campaigns_light(session)
        approvals = await get_pending_approvals(session)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "campaigns": campaigns,
            "pending_approvals": len(approvals),
        },
    )


@app.get("/campaign/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(request: Request, campaign_id: str) -> HTMLResponse:
    """Campaign detail page."""
    cid = UUID(campaign_id)
    async with get_session() as session:
        campaign = await _get_campaign_light(session, cid)
        variants = await _get_variants_light(session, cid)
        elements = await get_element_rankings(session, cid)
        interactions = await get_top_interactions(session, cid)
        cycles = await get_recent_cycles(session, cid, limit=10)
        approvals = await get_pending_approvals(session, campaign_id=cid)

    return templates.TemplateResponse(
        request,
        "campaign.html",
        {
            "campaign": campaign,
            "variants": variants,
            "elements": elements,
            "interactions": interactions,
            "cycles": cycles,
            "approvals": approvals,
        },
    )


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------


@app.get("/api/campaigns")
async def api_campaigns(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List active campaigns the authenticated user can access."""
    campaigns = await get_user_campaigns(session, user.id)
    return _serialize(campaigns)


@app.get("/api/campaigns/{campaign_id}/variants")
async def api_variants(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List active variants for a campaign."""
    variants = await _get_variants_light(session, campaign_id)
    return _serialize(variants)


@app.get("/api/campaigns/{campaign_id}/elements")
async def api_elements(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Element performance rankings for a campaign."""
    elements = await get_element_rankings(session, campaign_id)
    return _serialize(elements)


@app.get("/api/campaigns/{campaign_id}/interactions")
async def api_interactions(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Top element interactions for a campaign."""
    interactions = await get_top_interactions(session, campaign_id)
    return _serialize(interactions)


@app.get("/api/campaigns/{campaign_id}/cycles")
async def api_cycles(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Recent optimization cycles for a campaign."""
    cycles = await get_recent_cycles(session, campaign_id)
    return _serialize(cycles)


@app.get("/api/gene-pool")
async def api_gene_pool(
    slot: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Gene pool entries, optionally filtered by slot."""
    entries = await list_gene_pool_entries(session, slot_name=slot)
    return _serialize(entries)


@app.get("/api/approvals")
async def api_approvals(
    campaign_id: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Pending approval queue items scoped to the authenticated user."""
    user_campaigns = await get_user_campaigns(session, user.id)
    user_campaign_ids = {c.id for c in user_campaigns}

    if campaign_id:
        cid = UUID(campaign_id)
        if cid not in user_campaign_ids:
            raise HTTPException(status_code=404, detail="not found")
        items = await get_pending_approvals(session, campaign_id=cid)
    else:
        # Fetch approvals for all of the user's campaigns
        from src.db.queries import get_pending_approvals_for_campaigns

        items = await get_pending_approvals_for_campaigns(
            session, campaign_ids=list(user_campaign_ids)
        )
    return _serialize(items)


# ---------------------------------------------------------------------------
# Weekly review flow (tokenized, no-login)
# ---------------------------------------------------------------------------


_ALLOWED_SUGGESTION_SLOTS = {"headline", "subhead", "cta_text"}


async def _campaign_from_token(token: str) -> UUID:
    """Verify a review token and return the embedded campaign_id.

    Raises HTTPException(401) on invalid/expired tokens.
    """
    campaign_id = verify_review_token(token)
    if campaign_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired review token")
    return campaign_id


@app.get("/review/{token}", response_class=HTMLResponse)
async def review_page(request: Request, token: str) -> HTMLResponse:
    """No-login review page for weekly proposed variants.

    Verifies the HMAC-signed token, loads pending proposals and the gene
    pool, and renders the review UI.
    """
    campaign_id = verify_review_token(token)
    if campaign_id is None:
        return HTMLResponse(
            content=(
                "<h1>Link expired</h1>"
                "<p>This review link is no longer valid. "
                "Wait for the next weekly report to get a fresh link.</p>"
            ),
            status_code=401,
        )

    async with get_session() as session:
        campaign = await _get_campaign_light(session, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")

        proposed = await load_proposed_variants(session, campaign_id)
        gene_pool = await list_gene_pool_entries(session)

    # Group gene pool entries by slot for the suggestion form
    gene_pool_by_slot: dict[str, list[Any]] = {}
    for entry in gene_pool:
        gene_pool_by_slot.setdefault(entry.slot_name, []).append(entry)

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "token": token,
            "campaign": campaign,
            "proposed_variants": proposed,
            "gene_pool_by_slot": gene_pool_by_slot,
            "allowed_suggestion_slots": sorted(_ALLOWED_SUGGESTION_SLOTS),
        },
    )


# ---------------------------------------------------------------------------
# Public compliance pages (no auth required — Meta App Review)
# ---------------------------------------------------------------------------


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request) -> HTMLResponse:
    """Public privacy policy page required by Meta App Review."""
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "privacy.html",
        {"contact_email": settings.report_email_from},
    )


@app.get("/data-deletion/{confirmation_code}", response_class=HTMLResponse)
async def data_deletion_status_page(request: Request, confirmation_code: str) -> HTMLResponse:
    """Public data-deletion status page returned to Meta after deauth.

    Meta (or the user) can visit this URL to verify that the data
    deletion was completed. The ``confirmation_code`` is returned
    in the webhook response JSON.
    """
    async with get_session() as session:
        deletion = await get_data_deletion_request(session, confirmation_code)
    if deletion is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")

    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "data_deletion.html",
        {
            "deletion": deletion,
            "contact_email": settings.report_email_from,
        },
    )


@app.get("/api/data-deletion/{confirmation_code}/status")
async def api_data_deletion_status(confirmation_code: str) -> JSONResponse:
    """JSON endpoint for the React data-deletion status page."""
    async with get_session() as session:
        deletion = await get_data_deletion_request(session, confirmation_code)
    if deletion is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")

    return JSONResponse({
        "confirmation_code": deletion.confirmation_code,
        "status": deletion.status,
        "requested_at": deletion.requested_at.isoformat(),
    })


@app.post("/api/webhooks/meta/deauthorize")
async def meta_deauthorize_webhook(request: Request) -> JSONResponse:
    """Meta data-deletion / deauthorization callback.

    When a user removes the app from Facebook Settings → Business
    Integrations, Meta POSTs a ``signed_request`` form field here.
    We verify the HMAC signature, delete the connection, and return
    the required JSON with a status URL + confirmation code.

    Reference:
    https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
    """
    from src.dashboard.meta_webhooks import (
        generate_confirmation_code,
        parse_signed_request,
    )

    settings = get_settings()
    if not settings.meta_app_secret:
        logger.error("META_APP_SECRET not configured — cannot verify deauth webhook")
        raise HTTPException(status_code=500, detail="Server misconfigured")

    form = await request.form()
    signed_request = form.get("signed_request")
    if not signed_request or not isinstance(signed_request, str):
        raise HTTPException(status_code=400, detail="Missing signed_request")

    try:
        payload = parse_signed_request(signed_request, settings.meta_app_secret)
    except ValueError:
        logger.warning("Invalid signed_request in deauthorize webhook")
        raise HTTPException(status_code=403, detail="Invalid signature")

    confirmation_code = generate_confirmation_code()

    async with get_session() as session:
        user_id = await delete_meta_connection_by_meta_user_id(session, payload.user_id)
        await create_data_deletion_request(
            session,
            confirmation_code=confirmation_code,
            meta_user_id=payload.user_id,
            user_id=user_id,
        )

    status_url = f"{settings.api_base_url}/data-deletion/{confirmation_code}"
    logger.info(
        "Meta deauthorize: meta_user=%s user=%s code=%s",
        payload.user_id,
        user_id,
        confirmation_code,
    )

    return JSONResponse({"url": status_url, "confirmation_code": confirmation_code})


# ---------------------------------------------------------------------------
# Beta signup (public, no auth)
# ---------------------------------------------------------------------------


class BetaSignupRequest(BaseModel):
    email: str


@app.post("/api/beta-signup", status_code=201)
@limiter.limit("10/minute")
async def api_beta_signup(request: Request, body: BetaSignupRequest) -> JSONResponse:
    """Collect an email for the beta waitlist. Public, rate-limited.

    First-time signups trigger a Kleiber-branded confirmation email.
    Duplicates return 201 silently (no info leak) and are *not* re-sent.
    """
    from src.db.tables import BetaSignup
    from src.reports.auth_email import send_beta_signup_confirmation

    email = body.email.strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="Invalid email")

    async with get_session() as session:
        existing = await session.execute(
            select(BetaSignup).where(BetaSignup.email == email)
        )
        if existing.scalar_one_or_none() is not None:
            # Already signed up — return success silently (don't leak info)
            return JSONResponse({"status": "ok"}, status_code=201)

        session.add(BetaSignup(email=email))
        await session.flush()

    logger.info("Beta signup: %s", email)

    # Fire-and-forget confirmation email. Failures are logged inside the
    # sender; we never surface them to the caller so an email outage
    # doesn't break signups.
    async def _send_confirmation() -> None:
        try:
            await send_beta_signup_confirmation(email)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Beta confirmation send failed for %s: %s", email, exc)

    asyncio.create_task(_send_confirmation())

    return JSONResponse({"status": "ok"}, status_code=201)


# ---------------------------------------------------------------------------


async def _load_approval_or_404(session, approval_id: UUID, campaign_id: UUID) -> None:
    """Verify an approval exists and belongs to the given campaign."""
    from src.db.tables import ApprovalQueueItem

    stmt = select(ApprovalQueueItem).where(ApprovalQueueItem.id == approval_id)
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if item.campaign_id != campaign_id:
        raise HTTPException(status_code=403, detail="Wrong campaign")


@app.post("/api/approvals/{approval_id}/approve")
@limiter.limit("60/hour")
async def api_approve(
    request: Request,
    approval_id: str,
    token: str = Form(...),
) -> JSONResponse:
    """Approve a pending variant. Verified by the review token."""
    campaign_id = await _campaign_from_token(token)
    try:
        aid = UUID(approval_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid approval id") from exc

    async with get_session() as session:
        await _load_approval_or_404(session, aid, campaign_id)
        item = await approve_variant(
            session,
            approval_id=aid,
            reviewer=f"web:{campaign_id}",
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Approval not found")

    return JSONResponse({"status": "approved", "approval_id": str(aid)})


@app.post("/api/approvals/{approval_id}/reject")
@limiter.limit("60/hour")
async def api_reject(
    request: Request,
    approval_id: str,
    token: str = Form(...),
    reason: str = Form("user_rejected"),
) -> JSONResponse:
    """Reject a pending variant. Verified by the review token."""
    campaign_id = await _campaign_from_token(token)
    try:
        aid = UUID(approval_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid approval id") from exc

    async with get_session() as session:
        await _load_approval_or_404(session, aid, campaign_id)
        item = await reject_variant(
            session,
            approval_id=aid,
            reason=reason,
            reviewer=f"web:{campaign_id}",
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Approval not found")

    return JSONResponse({"status": "rejected", "approval_id": str(aid)})


@app.post("/api/gene-pool/suggest")
@limiter.limit("30/hour")
async def api_suggest_gene_pool(
    request: Request,
    token: str = Form(...),
    slot_name: str = Form(...),
    slot_value: str = Form(...),
    description: str = Form(""),
) -> JSONResponse:
    """Accept a user creative suggestion and add it to the gene pool.

    Suggestions go in as active (user is a trusted authority on their
    own brand) with source='user_suggestion'. The next weekly generation
    pass will pick them up automatically.
    """
    campaign_id = await _campaign_from_token(token)

    # Guard: only allow copy slots, not media assets or audience targeting
    if slot_name not in _ALLOWED_SUGGESTION_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Suggestions are only allowed for: {sorted(_ALLOWED_SUGGESTION_SLOTS)}",
        )

    slot_value = slot_value.strip()
    if not slot_value:
        raise HTTPException(status_code=400, detail="Value cannot be empty")
    if len(slot_value) > 500:
        raise HTTPException(status_code=400, detail="Value too long (max 500 chars)")

    async with get_session() as session:
        try:
            entry = await add_gene_pool_entry(
                session,
                slot_name=slot_name,
                slot_value=slot_value,
                description=description.strip()
                or f"Suggested via weekly review by campaign {campaign_id}",
                source="user_suggestion",
            )
        except HTTPException:
            raise
        except Exception as exc:  # IntegrityError on duplicate
            logger.info("Gene pool suggestion rejected: %s", exc)
            raise HTTPException(
                status_code=409,
                detail="This value already exists in the gene pool",
            ) from exc

    return JSONResponse(
        {
            "status": "added",
            "slot_name": entry.slot_name,
            "slot_value": entry.slot_value,
        }
    )


# ===========================================================================
# Phase 2 — Authenticated JSON API
#
# Everything below this line is consumed by the React dashboard in
# ``frontend/``. Endpoints use cookie-based auth (session_token) plus a
# double-submit CSRF token on mutating requests.
# ===========================================================================


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _lowercase_and_validate(cls, v: str) -> str:
        # Minimal email sanity check — we don't want to drag in the
        # ``email-validator`` dependency just for a sign-in form.
        s = v.strip().lower()
        if "@" not in s or "." not in s.split("@", 1)[1] or len(s) > 254:
            raise ValueError("invalid email address")
        return s


class UserCampaignOut(BaseModel):
    id: UUID
    name: str
    is_active: bool


class MetaConnectResponse(BaseModel):
    auth_url: str


class MetaConnectionStatus(BaseModel):
    connected: bool
    meta_user_id: str | None = None
    connected_at: datetime | None = None
    token_expires_at: datetime | None = None
    # Phase G — enumerated once at OAuth callback time. Empty lists
    # here mean the user has no reachable accounts/pages (brand-new
    # Facebook account) and the import flow will prompt them to
    # create one in Meta Ads Manager first.
    available_ad_accounts: list[MetaAdAccountInfo] = Field(default_factory=list)
    available_pages: list[MetaPageInfo] = Field(default_factory=list)
    default_ad_account_id: str | None = None
    default_page_id: str | None = None


class MeResponse(BaseModel):
    id: UUID
    email: str
    campaigns: list[UserCampaignOut]


class DailyDatesResponse(BaseModel):
    dates: list[str]  # ISO YYYY-MM-DD, newest first


class WeekDescriptor(BaseModel):
    week_start: date
    week_end: date
    label: str  # e.g., "Mar 30 - Apr 5"


class WeeklyIndexResponse(BaseModel):
    weeks: list[WeekDescriptor]


class GenePoolEntryOut(BaseModel):
    id: UUID
    slot_name: str
    slot_value: str
    description: str | None
    source: str | None


class ExperimentsResponse(BaseModel):
    """Payload for the ``/experiments`` page.

    Phase H: ``pending_approvals`` is the new unified discriminated
    union covering new variants + pause/scale/promote proposals, and
    is what the updated frontend renders. ``proposed_variants`` is
    kept in the response purely for the weekly-email report code path
    that still imports ``ProposedVariant`` directly; it's a filtered
    subset of ``pending_approvals`` and the dashboard UI ignores it.
    """

    proposed_variants: list[ProposedVariant]
    pending_approvals: list[PendingApproval]
    gene_pool_by_slot: dict[str, list[GenePoolEntryOut]]
    allowed_suggestion_slots: list[str]


class ApproveResponse(BaseModel):
    status: str
    approval_id: UUID


class RejectRequest(BaseModel):
    reason: str = "user_rejected"


class SuggestRequest(BaseModel):
    slot_name: str
    slot_value: str
    description: str | None = None


class SuggestResponse(BaseModel):
    status: str
    slot_name: str
    slot_value: str


class UsageServiceBreakdown(BaseModel):
    """Cost + call count for a single ``service`` bucket."""

    service: str  # 'llm' | 'meta_api' | 'email'
    cost_usd: Decimal
    calls: int


class UsageCampaignBreakdown(BaseModel):
    """Cost + call count for a single campaign.

    ``campaign_id`` and ``campaign_name`` may both be ``None`` when
    the rows were written without a campaign (e.g., standalone
    copywriter runs) or the campaign has since been deleted —
    usage_log uses ``ON DELETE SET NULL`` for its FKs.
    """

    campaign_id: UUID | None = None
    campaign_name: str | None = None
    cost_usd: Decimal
    calls: int


class UsageDayBreakdown(BaseModel):
    """Cost + call count for a single UTC day."""

    day: date
    cost_usd: Decimal
    calls: int


class UsageSummary(BaseModel):
    """Aggregated usage/cost rollup for the signed-in user.

    Powers the "this month" cost tile on the dashboard and any
    per-user budgeting conversations. Dollar amounts are rounded to
    six decimal places to match the precision of
    ``usage_log.cost_usd``.
    """

    from_date: date
    to_date: date
    total_cost_usd: Decimal
    total_calls: int
    by_service: list[UsageServiceBreakdown]
    by_campaign: list[UsageCampaignBreakdown]
    by_day: list[UsageDayBreakdown]


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _set_auth_cookies(response: Response, user_id: UUID) -> tuple[str, str]:
    """Write the session_token + csrf_token cookies on ``response``.

    Returns the raw (session_token, csrf_token) pair for test assertions.
    """
    settings = get_settings()
    session_token = create_session_token(user_id)
    csrf_token = generate_csrf_token()
    max_age = settings.auth_session_ttl_days * 86400

    cookie_kwargs: dict[str, Any] = {
        "max_age": max_age,
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": "none" if settings.cookie_secure else "lax",
    }
    if settings.cookie_domain:
        cookie_kwargs["domain"] = settings.cookie_domain

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        **cookie_kwargs,
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        **cookie_kwargs,
    )
    return session_token, csrf_token


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    cookie_kwargs: dict[str, Any] = {
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": "none" if settings.cookie_secure else "lax",
    }
    if settings.cookie_domain:
        cookie_kwargs["domain"] = settings.cookie_domain
    response.delete_cookie("session_token", **cookie_kwargs)
    response.delete_cookie("csrf_token", **cookie_kwargs)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@app.post("/api/auth/magic-link", status_code=204)
@limiter.limit("20/hour")
async def api_magic_link(
    request: Request,
    body: MagicLinkRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Email a sign-in link to ``body.email``.

    Self-serve: the link is sent for *any* well-formed email; the user
    row is created lazily inside ``api_auth_verify`` on first successful
    verify. Returning 204 regardless of whether the email already exists
    prevents enumeration.

    Rate-limited at two layers — 20/hour per client IP (via slowapi
    decorator) and 5/minute per email (in-process sliding window). A
    429 response is returned whichever limit fires first. Dev mode logs
    the link to stdout instead of sending (see
    ``src/reports/auth_email.py``).
    """
    if _check_email_rate_limit(body.email):
        logger.info("Magic-link email rate limit hit for %s", body.email)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "detail": "Too many magic-link requests for this email",
            },
        )

    settings = get_settings()
    token = create_magic_link_token(body.email)
    link = f"{settings.api_base_url.rstrip('/')}/api/auth/verify?token={token}"
    try:
        await send_magic_link(body.email, link)
    except Exception as exc:  # noqa: BLE001 — delivery failure shouldn't leak
        logger.warning("Magic-link delivery failed for %s: %s", body.email, exc)
    return Response(status_code=204)


@app.get("/api/auth/verify")
async def api_auth_verify(
    token: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Consume a magic-link token and redirect to the frontend dashboard.

    Ordering matters:

    1. Verify the HMAC + expiry. Bad → 302 invalid_link.
    2. Atomically insert the token hash into ``magic_links_consumed``.
       If the hash already exists it's a replay → 302 invalid_link. This
       is the single-use guarantee.
    3. Look up the user by email; if missing, create one (self-serve).
       The create is race-safe: on ``IntegrityError`` we re-read.
    4. Touch ``last_login_at`` and issue cookies.

    On success sets the ``session_token`` + ``csrf_token`` cookies and
    302-redirects to ``<frontend_base_url>/dashboard``.
    """
    settings = get_settings()
    frontend = settings.frontend_base_url.rstrip("/")
    invalid_redirect = RedirectResponse(
        url=f"{frontend}/sign-in?error=invalid_link",
        status_code=302,
    )

    email = verify_magic_link_token(token)
    if email is None:
        return invalid_redirect

    # Single-use enforcement: first verify wins, every replay hits the
    # ON CONFLICT branch and bounces.
    token_hash = hash_magic_link_token(token)
    newly_consumed = await consume_magic_link_token(session, token_hash)
    if not newly_consumed:
        logger.info("Rejected replay of consumed magic-link token")
        return invalid_redirect

    # Self-serve signup: unknown email → create user on first successful
    # verify. Concurrent verifies for a brand-new email race on the unique
    # constraint; catch IntegrityError and re-read.
    user = await get_user_by_email(session, email)
    if user is None:
        try:
            user = await create_user(session, email)
            logger.info("Self-serve signup: created user %s", email)
        except IntegrityError:
            await session.rollback()
            user = await get_user_by_email(session, email)
        if user is None:
            # Shouldn't happen — the unique constraint was violated by a
            # concurrent insert but we still can't find the row. Fail closed.
            logger.error("Self-serve signup race lost for %s", email)
            return invalid_redirect

    await touch_last_login(session, user.id)

    response = RedirectResponse(url=f"{frontend}/dashboard", status_code=302)
    _set_auth_cookies(response, user.id)
    return response


@app.post("/api/auth/logout", status_code=204)
async def api_logout(
    _: None = Depends(require_csrf),
    user: User = Depends(get_current_user),
) -> Response:
    """Clear the session + CSRF cookies. Requires a valid session."""
    response = Response(status_code=204)
    _clear_auth_cookies(response)
    return response


@app.get("/api/me", response_model=MeResponse)
async def api_me(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> MeResponse:
    """Return the current user and the campaigns they can access."""
    campaigns = await get_user_campaigns(session, user.id)
    return MeResponse(
        id=user.id,
        email=user.email,
        campaigns=[UserCampaignOut(id=c.id, name=c.name, is_active=c.is_active) for c in campaigns],
    )


# ---------------------------------------------------------------------------
# Meta OAuth (Phase B)
# ---------------------------------------------------------------------------


@app.post("/api/me/meta/connect", response_model=MetaConnectResponse)
async def api_meta_connect(
    _: None = Depends(require_csrf),
    user: User = Depends(get_current_user),
) -> MetaConnectResponse:
    """Return the Meta authorize URL for the current user to start OAuth.

    The frontend receives the URL and does
    ``window.location.href = auth_url``. The ``state`` parameter is a
    signed nonce binding this OAuth start to the user — we verify it on
    the callback and refuse to exchange the code if it doesn't match.
    """
    state = create_oauth_state_token(user.id)
    auth_url = build_meta_oauth_url(state)
    return MetaConnectResponse(auth_url=auth_url)


@app.get("/api/auth/meta/callback")
async def api_meta_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Handle the Meta OAuth callback redirect.

    Unauthenticated by design — Meta's redirect is a top-level browser
    navigation and doesn't carry our session cookie reliably. We bind
    the flow to a user via the HMAC-signed ``state`` nonce instead.

    Always redirects to the frontend dashboard with a query param:

    - ``?meta_connected=1`` on success
    - ``?meta_error=<code>`` on any failure

    Failures are logged server-side but the URL error code is coarse on
    purpose to avoid leaking Meta API internals into the browser.
    """
    settings = get_settings()
    frontend = settings.frontend_base_url.rstrip("/")

    def _fail(code_: str) -> RedirectResponse:
        return RedirectResponse(url=f"{frontend}/dashboard?meta_error={code_}", status_code=302)

    if error:
        logger.info(
            "Meta OAuth user declined or errored: %s (%s)",
            error,
            error_description,
        )
        return _fail("declined")

    if not code or not state:
        return _fail("missing_params")

    user_id = verify_oauth_state_token(state)
    if user_id is None:
        logger.info("Meta OAuth callback with invalid/expired state nonce")
        return _fail("invalid_state")

    try:
        short = await exchange_code_for_token(code)
        long_lived = await exchange_short_for_long_lived(short.access_token)
        meta_user_id = await fetch_meta_user_id(long_lived.access_token)
    except MetaOAuthError as exc:
        logger.warning("Meta OAuth exchange failed for user %s: %s", user_id, exc)
        return _fail("exchange_failed")

    # Phase G — enumerate the token's reachable ad accounts + Pages so
    # the import flow can show real per-user dropdowns instead of
    # pointing at global settings. Failure here isn't fatal to the
    # token exchange itself, but without this data the user can't
    # pick an account on the import page — surface a distinct error
    # code so the UI can prompt an explicit retry.
    try:
        ad_accounts = await fetch_meta_ad_accounts(long_lived.access_token)
        pages = await fetch_meta_pages(long_lived.access_token)
    except MetaOAuthError as exc:
        logger.warning("Meta asset enumeration failed for user %s: %s", user_id, exc)
        return _fail("enumeration_failed")

    try:
        ciphertext = encrypt_token(long_lived.access_token)
    except (MetaTokenCryptoError, ValueError) as exc:
        logger.error("Meta token encryption failed: %s", exc)
        return _fail("crypto_error")

    scopes = [s.strip() for s in settings.meta_oauth_scopes.split(",") if s.strip()]

    # Auto-pick defaults when the user has exactly one of each. This
    # spares single-account users (the common SMB case) from ever
    # seeing the picker. Users with multiple accounts/Pages get NULL
    # here and the import page forces a choice.
    default_ad_account_id = ad_accounts[0].id if len(ad_accounts) == 1 else None
    default_page_id = pages[0].id if len(pages) == 1 else None

    await upsert_meta_connection(
        session,
        user_id=user_id,
        meta_user_id=meta_user_id,
        encrypted_access_token=ciphertext,
        token_expires_at=long_lived.expires_at,
        scopes=scopes,
        available_ad_accounts=[a.model_dump() for a in ad_accounts],
        available_pages=[p.model_dump() for p in pages],
        default_ad_account_id=default_ad_account_id,
        default_page_id=default_page_id,
    )
    logger.info(
        "Meta OAuth success: app_user=%s meta_user=%s accounts=%d pages=%d",
        user_id,
        meta_user_id,
        len(ad_accounts),
        len(pages),
    )
    return RedirectResponse(url=f"{frontend}/dashboard?meta_connected=1", status_code=302)


@app.get("/api/me/meta/status", response_model=MetaConnectionStatus)
async def api_meta_status(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> MetaConnectionStatus:
    """Return the current user's Meta connection status.

    Does **not** decrypt or return the access token — only the
    ``meta_user_id`` and metadata the UI needs to show "connected as
    <id>" or prompt a re-connect.
    """
    connection = await get_meta_connection(session, user.id)
    if connection is None:
        return MetaConnectionStatus(connected=False)
    # Coerce the stored JSONB dicts back into the wire-shape Pydantic
    # models. Bad rows (e.g. if a future schema tweak drifted from
    # the JSONB payload) skip silently rather than 500ing the whole
    # status endpoint — the UI just sees an empty list.
    ad_accounts: list[MetaAdAccountInfo] = []
    for raw in connection.available_ad_accounts or []:
        try:
            ad_accounts.append(MetaAdAccountInfo.model_validate(raw))
        except Exception:  # noqa: BLE001 — tolerate stale JSONB shapes
            logger.warning(
                "Dropping malformed available_ad_accounts entry for user %s: %r",
                user.id,
                raw,
            )
    pages: list[MetaPageInfo] = []
    for raw in connection.available_pages or []:
        try:
            pages.append(MetaPageInfo.model_validate(raw))
        except Exception:  # noqa: BLE001
            logger.warning(
                "Dropping malformed available_pages entry for user %s: %r",
                user.id,
                raw,
            )
    return MetaConnectionStatus(
        connected=True,
        meta_user_id=connection.meta_user_id,
        connected_at=connection.connected_at,
        token_expires_at=connection.token_expires_at,
        available_ad_accounts=ad_accounts,
        available_pages=pages,
        default_ad_account_id=connection.default_ad_account_id,
        default_page_id=connection.default_page_id,
    )


@app.delete("/api/me/meta/connection", status_code=204)
async def api_meta_disconnect(
    _: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete the current user's Meta connection (user-initiated disconnect).

    Phase C and beyond will refuse to run cycles for campaigns whose
    owner has no connection, so disconnecting effectively pauses the
    user's campaigns until they re-connect.
    """
    await delete_meta_connection(session, user.id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Self-serve campaign import (Phase D)
# ---------------------------------------------------------------------------


@app.get(
    "/api/me/meta/campaigns",
    response_model=ImportableCampaignsResponse,
)
async def api_meta_importable_campaigns(
    ad_account_id: str | None = Query(
        default=None,
        description=(
            "Meta ad account id (e.g. act_123456). Optional — defaults to "
            "the user's default_ad_account_id. Required when the user has "
            "multiple accounts with no default."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> ImportableCampaignsResponse:
    """Return the signed-in user's Meta campaigns for the picker.

    Also returns the user's current quota usage + the full set of
    ad accounts and Pages their token can reach, so the UI can
    render the account dropdown without a second roundtrip. Requires
    Meta to be connected first; otherwise 409.

    If the user has multiple ad accounts and hasn't picked one yet,
    returns HTTP 400 ``pick_account_first`` — the UI should force a
    dropdown selection before calling again.
    """
    try:
        return await list_importable_campaigns(session, user.id, ad_account_id=ad_account_id)
    except MetaConnectionMissing as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "meta_not_connected", "message": str(exc)},
        ) from exc
    except MetaTokenExpired as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "meta_token_expired", "message": str(exc)},
        ) from exc
    except MultipleAdAccountsNoDefault as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "pick_account_first", "message": str(exc)},
        ) from exc
    except AdAccountNotAllowed as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "account_not_in_allowlist", "message": str(exc)},
        ) from exc


@app.post(
    "/api/me/meta/campaigns/import",
    response_model=CampaignImportResult,
)
@limiter.limit("10/hour")
async def api_meta_import_campaigns(
    request: Request,
    payload: CampaignImportRequest,
    _: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> CampaignImportResult:
    """Bulk-import Meta campaigns chosen from the picker.

    Each campaign is attempted independently: one failure doesn't
    roll back earlier successes. Partial success is the common
    case — the response body carries ``imported`` and ``failed``
    arrays and the endpoint always returns 200.

    The 5-campaign cap (``settings.max_campaigns_per_user``) is
    enforced before the first write; if a user is already at the
    cap the whole request is rejected with a single
    ``CampaignCapExceeded`` error entry.
    """
    settings = get_settings()
    imported: list = []
    failed: list[CampaignImportFailure] = []

    # Short-circuit if the user is already over cap — no point
    # doing any Meta calls at all.
    starting = await count_active_campaigns_for_user(session, user.id)
    if starting >= settings.max_campaigns_per_user:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "campaign_cap_exceeded",
                "current": starting,
                "maximum": settings.max_campaigns_per_user,
            },
        )

    for meta_id in payload.meta_campaign_ids:
        try:
            summary = await import_campaign(
                session=session,
                user_id=user.id,
                meta_campaign_id=meta_id,
                ad_account_id=payload.ad_account_id,
                page_id=payload.page_id,
                landing_page_url=payload.landing_page_url,
                overrides=payload.overrides,
            )
            imported.append(summary)
        except CampaignCapExceeded as exc:
            failed.append(CampaignImportFailure(meta_campaign_id=meta_id, error=str(exc)))
            # Cap hit mid-batch — everything after this will hit
            # the same wall, so stop and let the UI show partial.
            break
        except CampaignAlreadyImported as exc:
            failed.append(CampaignImportFailure(meta_campaign_id=meta_id, error=str(exc)))
        except AdAccountNotAllowed as exc:
            # Cross-user guard tripped — the whole batch is tainted,
            # fail hard with HTTP 400 rather than partial success.
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "account_not_in_allowlist",
                    "message": str(exc),
                },
            ) from exc
        except (MetaConnectionMissing, MetaTokenExpired) as exc:
            failed.append(CampaignImportFailure(meta_campaign_id=meta_id, error=str(exc)))
            break  # connection issue → no retry helps
        except Exception as exc:  # noqa: BLE001 — we want to surface any error
            logger.exception(
                "Unexpected error importing campaign %s for user %s",
                meta_id,
                user.id,
            )
            failed.append(
                CampaignImportFailure(meta_campaign_id=meta_id, error=f"internal_error: {exc}")
            )

    quota_after = await count_active_campaigns_for_user(session, user.id)
    return CampaignImportResult(
        imported=imported,
        failed=failed,
        quota_used_after=quota_after,
        quota_max=settings.max_campaigns_per_user,
    )


# ---------------------------------------------------------------------------
# Per-user usage + cost rollup (Phase E)
# ---------------------------------------------------------------------------


def _default_usage_window() -> tuple[date, date]:
    """Return (from_date, to_date) covering the trailing 30 days.

    Both dates are inclusive; ``to_date`` is today in UTC.
    """
    today = datetime.now(UTC).date()
    return today - timedelta(days=29), today


@app.get("/api/me/usage", response_model=UsageSummary)
async def api_my_usage(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> UsageSummary:
    """Return a cost + call-count rollup for the current user.

    Aggregates ``usage_log`` rows (filtered by ``user_id``) between
    two inclusive UTC dates. If the range is omitted, defaults to
    the trailing 30 days. The response is structured for direct
    rendering in the dashboard "this month" tile:

    - ``total_cost_usd`` — single number for the prominent big-stat
    - ``by_service`` — LLM vs Meta vs email split
    - ``by_campaign`` — which campaigns are driving spend
    - ``by_day`` — sparkline-ready daily series

    Bounds: we cap the range at 366 days to protect the hypertable
    from accidental year-over-year scans.
    """
    default_from, default_to = _default_usage_window()
    range_from = from_date or default_from
    range_to = to_date or default_to

    if range_to < range_from:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_range", "message": "to must be >= from"},
        )
    if (range_to - range_from).days > 366:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "range_too_large",
                "message": "usage window is capped at 366 days",
            },
        )

    # Half-open [start, end) window so a single date returns one
    # full day's worth of rows regardless of timezone.
    start_ts = datetime.combine(range_from, datetime.min.time(), tzinfo=UTC)
    end_ts = datetime.combine(range_to + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    params = {
        "user_id": user.id,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }

    # Totals
    totals_row = (
        await session.execute(
            sa_text(
                """
                SELECT
                  COALESCE(SUM(cost_usd), 0) AS total_cost,
                  COALESCE(COUNT(*), 0)      AS total_calls
                FROM usage_log
                WHERE user_id = :user_id
                  AND recorded_at >= :start_ts
                  AND recorded_at <  :end_ts
                """
            ),
            params,
        )
    ).one()
    total_cost = Decimal(totals_row.total_cost or 0)
    total_calls = int(totals_row.total_calls or 0)

    # Per-service split
    service_rows = (
        await session.execute(
            sa_text(
                """
                SELECT
                  service,
                  COALESCE(SUM(cost_usd), 0) AS cost,
                  COUNT(*)                   AS calls
                FROM usage_log
                WHERE user_id = :user_id
                  AND recorded_at >= :start_ts
                  AND recorded_at <  :end_ts
                GROUP BY service
                ORDER BY cost DESC
                """
            ),
            params,
        )
    ).fetchall()
    by_service = [
        UsageServiceBreakdown(
            service=row.service,
            cost_usd=Decimal(row.cost or 0),
            calls=int(row.calls or 0),
        )
        for row in service_rows
    ]

    # Per-campaign split (LEFT JOIN so NULL campaign_ids still show up)
    campaign_rows = (
        await session.execute(
            sa_text(
                """
                SELECT
                  u.campaign_id              AS campaign_id,
                  c.name                     AS campaign_name,
                  COALESCE(SUM(u.cost_usd), 0) AS cost,
                  COUNT(*)                   AS calls
                FROM usage_log u
                LEFT JOIN campaigns c ON c.id = u.campaign_id
                WHERE u.user_id = :user_id
                  AND u.recorded_at >= :start_ts
                  AND u.recorded_at <  :end_ts
                GROUP BY u.campaign_id, c.name
                ORDER BY cost DESC
                """
            ),
            params,
        )
    ).fetchall()
    by_campaign = [
        UsageCampaignBreakdown(
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            cost_usd=Decimal(row.cost or 0),
            calls=int(row.calls or 0),
        )
        for row in campaign_rows
    ]

    # Per-day split — use DATE() in UTC to match the existing report
    # endpoints (we're not using time_bucket here because the dashboard
    # only ever asks for daily granularity).
    day_rows = (
        await session.execute(
            sa_text(
                """
                SELECT
                  DATE(recorded_at AT TIME ZONE 'UTC') AS day,
                  COALESCE(SUM(cost_usd), 0)           AS cost,
                  COUNT(*)                             AS calls
                FROM usage_log
                WHERE user_id = :user_id
                  AND recorded_at >= :start_ts
                  AND recorded_at <  :end_ts
                GROUP BY day
                ORDER BY day ASC
                """
            ),
            params,
        )
    ).fetchall()
    by_day = [
        UsageDayBreakdown(
            day=row.day,
            cost_usd=Decimal(row.cost or 0),
            calls=int(row.calls or 0),
        )
        for row in day_rows
    ]

    return UsageSummary(
        from_date=range_from,
        to_date=range_to,
        total_cost_usd=total_cost,
        total_calls=total_calls,
        by_service=by_service,
        by_campaign=by_campaign,
        by_day=by_day,
    )


# ---------------------------------------------------------------------------
# Authed report endpoints
# ---------------------------------------------------------------------------


@app.get(
    "/api/campaigns/{campaign_id}/reports/daily",
    response_model=DailyDatesResponse,
)
async def api_daily_dates(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> DailyDatesResponse:
    """Return the list of dates that have a daily report available.

    A "day with data" is any day that has at least one metric row for a
    variant in this campaign. We expose dates newest-first so the
    frontend can render them as a sidebar list.
    """
    # Exclude today — the metrics poller runs every few hours, so a
    # partial row for today's UTC date is always present while the
    # day is still in progress. Surfacing today in the date list
    # would produce an incomplete "daily report" with artificially
    # low spend / purchase totals. Only offer days that are fully
    # in the past (UTC) — the cron's report generation also scopes
    # to yesterday and earlier.
    stmt = sa_text(
        """
        SELECT DISTINCT DATE(m.recorded_at AT TIME ZONE 'UTC') AS day
        FROM metrics m
        JOIN variants v ON v.id = m.variant_id
        WHERE v.campaign_id = :campaign_id
          AND DATE(m.recorded_at AT TIME ZONE 'UTC') < (NOW() AT TIME ZONE 'UTC')::DATE
        ORDER BY day DESC
        LIMIT 180
        """
    )
    result = await session.execute(stmt, {"campaign_id": campaign_id})
    dates = [row[0].isoformat() for row in result.fetchall() if row[0] is not None]
    return DailyDatesResponse(dates=dates)


@app.get(
    "/api/campaigns/{campaign_id}/reports/daily/{report_date}",
    response_model=DailyReport,
)
async def api_daily_report(
    report_date: date,
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> DailyReport:
    """Return a full daily report for ``report_date``."""
    try:
        return await build_daily_report(session, campaign_id, report_date)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc


@app.get(
    "/api/campaigns/{campaign_id}/reports/weekly",
    response_model=WeeklyIndexResponse,
)
async def api_weekly_index(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> WeeklyIndexResponse:
    """Return all ISO weeks (Mon–Sun) that have metric data for this campaign."""
    stmt = sa_text(
        """
        SELECT DISTINCT
          DATE_TRUNC('week', m.recorded_at AT TIME ZONE 'UTC')::DATE AS week_start
        FROM metrics m
        JOIN variants v ON v.id = m.variant_id
        WHERE v.campaign_id = :campaign_id
        ORDER BY week_start DESC
        LIMIT 52
        """
    )
    result = await session.execute(stmt, {"campaign_id": campaign_id})
    weeks: list[WeekDescriptor] = []
    for row in result.fetchall():
        week_start: date = row[0]
        week_end = week_start + timedelta(days=6)
        label = f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}"
        weeks.append(WeekDescriptor(week_start=week_start, week_end=week_end, label=label))
    return WeeklyIndexResponse(weeks=weeks)


@app.get(
    "/api/campaigns/{campaign_id}/reports/weekly/{week_start}",
    response_model=WeeklyReport,
)
async def api_weekly_report(
    week_start: date,
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> WeeklyReport:
    """Return a full weekly report starting on ``week_start``.

    ``week_start`` must be a Monday. We do not enforce it here — the
    service just computes the Mon–Sun window from the provided date.
    """
    week_end = week_start + timedelta(days=6)
    try:
        return await build_weekly_report(
            session,
            campaign_id,
            week_start,
            week_end=week_end,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc


# ---------------------------------------------------------------------------
# Authed experiments endpoints
# ---------------------------------------------------------------------------


@app.get(
    "/api/campaigns/{campaign_id}/experiments",
    response_model=ExperimentsResponse,
)
async def api_experiments(
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
) -> ExperimentsResponse:
    """Return pending proposals + the gene pool + allowed suggestion slots.

    Phase H: the dashboard now shows a unified feed of proposals —
    new variants, pause requests, and budget changes. We build
    ``pending_approvals`` (the discriminated union the new UI
    renders) and keep ``proposed_variants`` populated for any
    back-compat caller that still wants the new_variant-only list.
    """
    pending = await load_pending_approvals(session, campaign_id)
    proposed = await load_proposed_variants(session, campaign_id)
    entries = await list_gene_pool_entries(session)

    gene_pool_by_slot: dict[str, list[GenePoolEntryOut]] = {}
    for entry in entries:
        gene_pool_by_slot.setdefault(entry.slot_name, []).append(
            GenePoolEntryOut(
                id=entry.id,
                slot_name=entry.slot_name,
                slot_value=entry.slot_value,
                description=entry.description,
                source=entry.source,
            )
        )

    return ExperimentsResponse(
        proposed_variants=proposed,
        pending_approvals=pending,
        gene_pool_by_slot=gene_pool_by_slot,
        allowed_suggestion_slots=sorted(_ALLOWED_SUGGESTION_SLOTS),
    )


@app.post(
    "/api/campaigns/{campaign_id}/experiments/{approval_id}/approve",
    response_model=ApproveResponse,
)
@limiter.limit("60/hour")
async def api_experiment_approve(
    request: Request,
    approval_id: UUID,
    _: None = Depends(require_csrf),
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> ApproveResponse:
    """Approve a pending proposal for this campaign.

    Phase H: the approve click is the user's verification. After
    flipping the DB flag we immediately hand off to
    :func:`execute_approved_action`, which resolves the per-campaign
    Meta adapter and pushes the side-effect (pause, scale, or — for
    new_variant rows — nothing; weekly deployer picks those up).

    If Meta rejects the change the executor rolls the approval back
    to rejected state and we return 502. The UI shows an error
    toast, the ad stays in its prior state, and the next cycle will
    re-queue a fresh proposal.
    """
    await _load_approval_or_404(session, approval_id, campaign_id)
    item = await approve_proposal(
        session,
        approval_id=approval_id,
        reviewer=f"user:{user.email}",
    )
    if item is None:
        raise HTTPException(status_code=404, detail="not found")

    result = await execute_approved_action(
        session,
        approval_id=approval_id,
        reviewer_user_id=user.id,
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.message)
    return ApproveResponse(status="approved", approval_id=approval_id)


@app.post(
    "/api/campaigns/{campaign_id}/experiments/{approval_id}/reject",
    response_model=ApproveResponse,
)
@limiter.limit("60/hour")
async def api_experiment_reject(
    request: Request,
    approval_id: UUID,
    body: RejectRequest,
    _: None = Depends(require_csrf),
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> ApproveResponse:
    """Reject a pending proposal for this campaign.

    Phase H: uses the generalised ``reject_proposal`` so pause/scale
    rows reject cleanly (no variant retirement) while
    new_variant/promote_winner rows retire their associated variant
    as before.
    """
    await _load_approval_or_404(session, approval_id, campaign_id)
    item = await reject_proposal(
        session,
        approval_id=approval_id,
        reason=body.reason,
        reviewer=f"user:{user.email}",
    )
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return ApproveResponse(status="rejected", approval_id=approval_id)


@app.post(
    "/api/campaigns/{campaign_id}/experiments/suggest",
    response_model=SuggestResponse,
)
@limiter.limit("30/hour")
async def api_experiment_suggest(
    request: Request,
    body: SuggestRequest,
    _: None = Depends(require_csrf),
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> SuggestResponse:
    """Add a user-suggested creative element to the gene pool."""
    if body.slot_name not in _ALLOWED_SUGGESTION_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Suggestions are only allowed for: {sorted(_ALLOWED_SUGGESTION_SLOTS)}",
        )

    slot_value = body.slot_value.strip()
    if not slot_value:
        raise HTTPException(status_code=400, detail="Value cannot be empty")
    if len(slot_value) > 500:
        raise HTTPException(status_code=400, detail="Value too long (max 500 chars)")

    description = (
        body.description.strip()
        if body.description
        else f"Suggested by {user.email} for campaign {campaign_id}"
    )

    try:
        entry = await add_gene_pool_entry(
            session,
            slot_name=body.slot_name,
            slot_value=slot_value,
            description=description,
            source="user_suggestion",
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="This value already exists in the gene pool"
        ) from exc

    return SuggestResponse(
        status="added",
        slot_name=entry.slot_name,
        slot_value=entry.slot_value,
    )
