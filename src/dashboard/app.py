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

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import noload

from src.db.engine import get_session
from src.db.queries import (
    get_element_rankings,
    get_pending_approvals,
    get_recent_cycles,
    get_top_interactions,
    list_gene_pool_entries,
)
from src.db.tables import Campaign, Variant, VariantStatus

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
