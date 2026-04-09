"""Lightweight read-only web dashboard for campaign monitoring.

Provides a FastAPI application with JSON API endpoints and a Jinja2-rendered
HTML dashboard. All endpoints are GET-only — this is a read-only view into
the system's state.

Dashboard queries use noload() to prevent eager loading of heavy relationship
chains (Campaign → Variant → Metric) that the dashboard doesn't need.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import noload

from src.dashboard.tokens import verify_review_token
from src.db.engine import get_session
from src.db.queries import (
    add_gene_pool_entry,
    approve_variant,
    get_element_rankings,
    get_pending_approvals,
    get_recent_cycles,
    get_top_interactions,
    list_gene_pool_entries,
    reject_variant,
)
from src.db.tables import Campaign, Variant
from src.services.weekly import load_proposed_variants

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app = FastAPI(
    title="Ad Creative Agent Dashboard",
    description="Read-only monitoring dashboard",
    docs_url=None,
    redoc_url=None,
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
