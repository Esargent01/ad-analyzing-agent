"""Discover ads created directly in Meta and pull them into Kleiber.

The metrics poller iterates over our local ``deployments`` table — it
never asks Meta "what ads are live in this campaign right now?". That
means any ad a user creates directly in Meta Ads Manager (bypassing the
``import_campaign`` flow) is invisible: its spend, its purchases, its
fatigue signals, its creative elements all live outside our reporting
loop until someone re-imports the campaign.

This module closes that gap by running a lightweight diff against Meta
before each poll cycle:

1. Call ``MetaAdapter.list_campaign_ads`` for the campaign's Meta id.
2. Subtract every ``platform_ad_id`` that already has a ``deployments``
   row for this campaign.
3. For each residual (new) ad, create one new ``Variant`` + one new
   ``Deployment`` row using the same extraction helpers the initial
   import uses, plus a freshly-claimed ``V{next}`` code.
4. Seed the gene pool with any new headlines / body copy / CTAs / images
   the new ad surfaces — so the generator has them available to remix
   on the next cycle.

Variants created here carry ``source = "discovered"`` so the operator
can always tell which variants Kleiber launched vs. which the user
created outside Kleiber and we merely adopted.

Ads we had but that are no longer on Meta are left alone. The poller
records zero metrics for deleted ads, and the existing fatigue /
status logic handles that case gracefully — a discovery-time cascade
would be more complexity than value.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.meta_factory import get_meta_adapter_for_campaign
from src.db.tables import (
    Campaign,
    Deployment,
    PlatformType,
    Variant,
    VariantStatus,
)
from src.services.campaign_import import (
    _extract_asset_feed_pool_entries,
    _extract_genome,
    _seed_gene_pool_entries,
)

logger = logging.getLogger(__name__)


async def _existing_platform_ad_ids(
    session: AsyncSession, campaign_id: UUID
) -> set[str]:
    """Every ``platform_ad_id`` already tracked under this campaign.

    Joins ``deployments`` → ``variants`` and filters to the campaign.
    Returned as a string set for cheap membership checks against the
    Meta ad list.
    """
    stmt = (
        select(Deployment.platform_ad_id)
        .join(Variant, Variant.id == Deployment.variant_id)
        .where(Variant.campaign_id == campaign_id)
    )
    result = await session.execute(stmt)
    return {str(row[0]) for row in result.fetchall() if row[0]}


async def _next_variant_code(
    session: AsyncSession, campaign_id: UUID
) -> int:
    """Return the next unused ``V{n}`` number for this campaign.

    Parses the numeric suffix off existing ``V{n}`` codes and returns
    ``max + 1`` (or ``1`` if the campaign has no variants yet). Robust
    to non-``V{n}``-shaped codes: anything that doesn't parse as int
    after stripping a leading ``V`` is ignored.
    """
    stmt = select(Variant.variant_code).where(Variant.campaign_id == campaign_id)
    result = await session.execute(stmt)
    highest = 0
    for (code,) in result.fetchall():
        if not isinstance(code, str) or not code.startswith("V"):
            continue
        try:
            n = int(code[1:])
        except ValueError:
            continue
        highest = max(highest, n)
    return highest + 1


async def sync_campaign_ads(
    session: AsyncSession,
    campaign: Campaign,
) -> int:
    """Pull in any Meta ads that exist in this campaign but not locally.

    Args:
        session: Active DB session — caller owns the transaction.
        campaign: The loaded ``Campaign`` ORM row. Must have a live
            ``platform_campaign_id`` (i.e. was imported from Meta) for
            this to do anything; returns 0 otherwise.

    Returns:
        Number of newly-created variants. 0 means "everything on Meta
        was already known about" (the steady-state happy path).

    Raises nothing on Meta-side failures beyond what the adapter raises —
    the caller is expected to wrap this in try/except if sync failures
    shouldn't break the broader cron step.
    """
    if not campaign.platform_campaign_id:
        logger.debug(
            "Campaign %s has no platform_campaign_id — skipping ad sync.",
            campaign.id,
        )
        return 0

    adapter = await get_meta_adapter_for_campaign(session, campaign.id)
    ads = await adapter.list_campaign_ads(str(campaign.platform_campaign_id))

    known = await _existing_platform_ad_ids(session, campaign.id)
    new_ads = [ad for ad in ads if str(ad.get("ad_id") or "") not in known]

    if not new_ads:
        logger.info(
            "Ad sync for campaign %s — no new ads (Meta: %d, local: %d).",
            campaign.id,
            len(ads),
            len(known),
        )
        return 0

    next_n = await _next_variant_code(session, campaign.id)
    created = 0
    genomes: list[dict[str, str]] = []
    asset_feed_extras: list[dict[str, str]] = []

    for ad in new_ads:
        genome = _extract_genome(ad)
        if not genome:
            # No usable slots — skip the variant row but don't fail the
            # whole sync. Common for test ads with no creative fields.
            logger.warning(
                "Skipping discovered ad %s (campaign %s): no extractable genome.",
                ad.get("ad_id"),
                campaign.id,
            )
            continue

        variant = Variant(
            campaign_id=campaign.id,
            variant_code=f"V{next_n}",
            genome=genome,
            status=VariantStatus.active,
            generation=0,
            parent_ids=[],
            hypothesis="Discovered in Meta — added outside Kleiber.",
            media_type=str(ad.get("media_type") or "unknown"),
            source="discovered",
        )
        session.add(variant)
        await session.flush()

        deployment = Deployment(
            variant_id=variant.id,
            platform=PlatformType.meta,
            platform_ad_id=str(ad["ad_id"]),
            platform_adset_id=str(ad.get("adset_id") or "") or None,
            # We don't know what Meta-side budget this ad was created
            # with — and for Advantage+ campaigns Meta allocates
            # dynamically anyway. Use the campaign's daily budget as a
            # local accounting record; the poller reads actual spend
            # from Meta insights, not from this column.
            daily_budget=Decimal(str(campaign.daily_budget)),
            is_active=(str(ad.get("status", "")).upper() == "ACTIVE"),
        )
        session.add(deployment)

        genomes.append(genome)
        asset_feed_extras.extend(_extract_asset_feed_pool_entries(ad))
        next_n += 1
        created += 1
        logger.info(
            "Discovered Meta ad %s in campaign %s — created variant %s.",
            ad["ad_id"],
            campaign.id,
            variant.variant_code,
        )

    if genomes or asset_feed_extras:
        await _seed_gene_pool_entries(session, genomes + asset_feed_extras)

    await session.flush()
    logger.info(
        "Ad sync for campaign %s — created %d new variant(s).",
        campaign.id,
        created,
    )
    return created
