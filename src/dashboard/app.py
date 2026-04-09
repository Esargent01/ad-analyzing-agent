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

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from src.config import get_settings
from src.dashboard.auth import (
    create_magic_link_token,
    create_session_token,
    generate_csrf_token,
    verify_magic_link_token,
)
from src.dashboard.deps import (
    get_current_user,
    get_db_session,
    require_campaign_access,
    require_csrf,
)
from src.dashboard.tokens import verify_review_token
from src.db.engine import get_session
from src.db.queries import (
    add_gene_pool_entry,
    approve_variant,
    create_user,
    get_element_rankings,
    get_pending_approvals,
    get_recent_cycles,
    get_top_interactions,
    get_user_by_email,
    get_user_campaigns,
    list_gene_pool_entries,
    reject_variant,
    touch_last_login,
)
from src.db.tables import Campaign, User, Variant
from src.models.reports import DailyReport, ProposedVariant, WeeklyReport
from src.reports.auth_email import send_magic_link
from src.services.reports import build_daily_report, build_weekly_report
from src.services.weekly import load_proposed_variants

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app = FastAPI(
    title="Ad Creative Agent Dashboard",
    description="Read-only monitoring dashboard + authenticated JSON API",
    docs_url=None,
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# CORS — only allow configured frontend origins
# ---------------------------------------------------------------------------


def _configured_origins() -> list[str]:
    settings = get_settings()
    return [
        o.strip() for o in settings.frontend_origins.split(",") if o.strip()
    ]


_cors_origins = _configured_origins()
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )


# ---------------------------------------------------------------------------
# Lightweight dashboard queries (avoid eager-loading metrics)
# ---------------------------------------------------------------------------


async def _get_campaigns_light(session):
    """Load campaigns without eager-loading variants/metrics."""
    stmt = (
        select(Campaign)
        .where(Campaign.is_active.is_(True))
        .options(noload("*"))
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_campaign_light(session, campaign_id: UUID):
    """Load a single campaign without eager-loading relationships."""
    stmt = (
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(noload("*"))
    )
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
        "dashboard.html",
        {
            "request": request,
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
        "campaign.html",
        {
            "request": request,
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
async def api_campaigns() -> list[dict]:
    """List all active campaigns."""
    async with get_session() as session:
        campaigns = await _get_campaigns_light(session)
    return _serialize(campaigns)


@app.get("/api/campaigns/{campaign_id}/variants")
async def api_variants(campaign_id: str) -> list[dict]:
    """List active variants for a campaign."""
    async with get_session() as session:
        variants = await _get_variants_light(session, UUID(campaign_id))
    return _serialize(variants)


@app.get("/api/campaigns/{campaign_id}/elements")
async def api_elements(campaign_id: str) -> list[dict]:
    """Element performance rankings for a campaign."""
    async with get_session() as session:
        elements = await get_element_rankings(session, UUID(campaign_id))
    return _serialize(elements)


@app.get("/api/campaigns/{campaign_id}/interactions")
async def api_interactions(campaign_id: str) -> list[dict]:
    """Top element interactions for a campaign."""
    async with get_session() as session:
        interactions = await get_top_interactions(session, UUID(campaign_id))
    return _serialize(interactions)


@app.get("/api/campaigns/{campaign_id}/cycles")
async def api_cycles(campaign_id: str) -> list[dict]:
    """Recent optimization cycles for a campaign."""
    async with get_session() as session:
        cycles = await get_recent_cycles(session, UUID(campaign_id))
    return _serialize(cycles)


@app.get("/api/gene-pool")
async def api_gene_pool(slot: str | None = None) -> list[dict]:
    """Gene pool entries, optionally filtered by slot."""
    async with get_session() as session:
        entries = await list_gene_pool_entries(session, slot_name=slot)
    return _serialize(entries)


@app.get("/api/approvals")
async def api_approvals(campaign_id: str | None = None) -> list[dict]:
    """Pending approval queue items."""
    cid = UUID(campaign_id) if campaign_id else None
    async with get_session() as session:
        items = await get_pending_approvals(session, campaign_id=cid)
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
        "review.html",
        {
            "request": request,
            "token": token,
            "campaign": campaign,
            "proposed_variants": proposed,
            "gene_pool_by_slot": gene_pool_by_slot,
            "allowed_suggestion_slots": sorted(_ALLOWED_SUGGESTION_SLOTS),
        },
    )


async def _load_approval_or_404(
    session, approval_id: UUID, campaign_id: UUID
) -> None:
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
async def api_approve(
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
async def api_reject(
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
async def api_suggest_gene_pool(
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
                description=description.strip() or f"Suggested via weekly review by campaign {campaign_id}",
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
    proposed_variants: list[ProposedVariant]
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


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _set_auth_cookies(
    response: Response, user_id: UUID
) -> tuple[str, str]:
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
async def api_magic_link(
    body: MagicLinkRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Email a sign-in link to ``body.email``.

    Always returns 204 whether the email exists or not — this prevents
    user enumeration. Dev mode logs the link to stdout instead of
    sending (see ``src/reports/auth_email.py``).
    """
    user = await get_user_by_email(session, body.email)
    if user is not None:
        settings = get_settings()
        token = create_magic_link_token(user.email)
        link = f"{settings.api_base_url.rstrip('/')}/api/auth/verify?token={token}"
        try:
            await send_magic_link(user.email, link)
        except Exception as exc:  # noqa: BLE001 — delivery failure shouldn't leak
            logger.warning("Magic-link delivery failed for %s: %s", user.email, exc)
    return Response(status_code=204)


@app.get("/api/auth/verify")
async def api_auth_verify(
    token: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Consume a magic-link token and redirect to the frontend dashboard.

    On success sets the ``session_token`` + ``csrf_token`` cookies and
    302-redirects to ``<frontend_base_url>/dashboard``. On failure
    redirects to ``<frontend_base_url>/sign-in?error=invalid_link``.
    """
    settings = get_settings()
    frontend = settings.frontend_base_url.rstrip("/")

    email = verify_magic_link_token(token)
    if email is None:
        return RedirectResponse(
            url=f"{frontend}/sign-in?error=invalid_link",
            status_code=302,
        )

    user = await get_user_by_email(session, email)
    if user is None:
        return RedirectResponse(
            url=f"{frontend}/sign-in?error=invalid_link",
            status_code=302,
        )

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
        campaigns=[
            UserCampaignOut(id=c.id, name=c.name, is_active=c.is_active)
            for c in campaigns
        ],
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
    stmt = sa_text(
        """
        SELECT DISTINCT DATE(m.recorded_at AT TIME ZONE 'UTC') AS day
        FROM metrics m
        JOIN variants v ON v.id = m.variant_id
        WHERE v.campaign_id = :campaign_id
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
        weeks.append(
            WeekDescriptor(week_start=week_start, week_end=week_end, label=label)
        )
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
    """Return pending proposals + the gene pool + allowed suggestion slots."""
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
        gene_pool_by_slot=gene_pool_by_slot,
        allowed_suggestion_slots=sorted(_ALLOWED_SUGGESTION_SLOTS),
    )


@app.post(
    "/api/campaigns/{campaign_id}/experiments/{approval_id}/approve",
    response_model=ApproveResponse,
)
async def api_experiment_approve(
    approval_id: UUID,
    _: None = Depends(require_csrf),
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> ApproveResponse:
    """Approve a pending proposal for this campaign."""
    await _load_approval_or_404(session, approval_id, campaign_id)
    item = await approve_variant(
        session,
        approval_id=approval_id,
        reviewer=f"user:{user.email}",
    )
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return ApproveResponse(status="approved", approval_id=approval_id)


@app.post(
    "/api/campaigns/{campaign_id}/experiments/{approval_id}/reject",
    response_model=ApproveResponse,
)
async def api_experiment_reject(
    approval_id: UUID,
    body: RejectRequest,
    _: None = Depends(require_csrf),
    campaign_id: UUID = Depends(require_campaign_access),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> ApproveResponse:
    """Reject a pending proposal for this campaign."""
    await _load_approval_or_404(session, approval_id, campaign_id)
    item = await reject_variant(
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
async def api_experiment_suggest(
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
