"""Deployer service for approved variants.

Handles the actual deployment of variants that have been approved through
the approval queue. Separated from the orchestrator so it can be triggered
from the CLI (approve yes --deploy-now) or at the start of the next cycle.
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


async def deploy_approved_variants(
    session: AsyncSession,
    adapter: BaseAdapter,
    campaign_id: uuid.UUID,
) -> list[dict]:
    """Deploy all approved-but-undeployed variants for a campaign.

    Finds variants with status='pending' that have approved=True in the
    approval queue, then creates ads on the platform and activates them.

    Returns a list of deployment summaries.
    """
    # Find approved variants awaiting deployment
    result = await session.execute(
        text("""
            SELECT aq.id AS approval_id,
                   v.id AS variant_id,
                   v.variant_code,
                   v.genome
            FROM approval_queue aq
            JOIN variants v ON v.id = aq.variant_id
            WHERE aq.campaign_id = :campaign_id
              AND aq.approved = TRUE
              AND v.status = 'pending'
            ORDER BY aq.submitted_at
        """),
        {"campaign_id": campaign_id},
    )
    rows = result.fetchall()

    if not rows:
        logger.info("No approved variants to deploy for campaign %s", campaign_id)
        return []

    # Get campaign info
    campaign_row = await session.execute(
        text("""
            SELECT platform, platform_campaign_id, daily_budget
            FROM campaigns WHERE id = :id
        """),
        {"id": campaign_id},
    )
    campaign = campaign_row.fetchone()
    if not campaign:
        logger.error("Campaign %s not found", campaign_id)
        return []

    platform = str(campaign[0])
    platform_campaign_id = str(campaign[1]) if campaign[1] else ""

    # Calculate remaining budget
    remaining_row = await session.execute(
        text("SELECT remaining_budget(:id)"),
        {"id": campaign_id},
    )
    remaining = remaining_row.scalar_one()
    remaining_budget = Decimal(str(remaining)) if remaining is not None else Decimal("0")

    if remaining_budget <= 0:
        logger.warning("No remaining budget for campaign %s", campaign_id)
        return []

    per_variant_budget = remaining_budget / len(rows)
    deployments: list[dict] = []

    for row in rows:
        variant_id = row[1]
        variant_code = str(row[2])
        genome = row[3] if isinstance(row[3], dict) else json.loads(row[3])

        try:
            # Resolve media asset
            media_info = None
            media_asset_name = genome.get("media_asset")
            if media_asset_name:
                asset_row = await session.execute(
                    text("""
                        SELECT asset_type, platform_id
                        FROM media_assets
                        WHERE campaign_id = :cid
                          AND name = :name
                          AND is_active = TRUE
                        LIMIT 1
                    """),
                    {"cid": campaign_id, "name": media_asset_name},
                )
                asset = asset_row.fetchone()
                if asset:
                    media_info = {
                        "asset_type": str(asset[0]),
                        "platform_id": str(asset[1]),
                    }

            # Look up audience metadata for targeting
            audience_meta = None
            audience_value = genome.get("audience")
            if audience_value:
                meta_row = await session.execute(
                    text("""
                        SELECT metadata
                        FROM gene_pool
                        WHERE slot_name = 'audience'
                          AND slot_value = :value
                          AND is_active = TRUE
                        LIMIT 1
                    """),
                    {"value": audience_value},
                )
                meta_result = meta_row.fetchone()
                if meta_result and meta_result[0]:
                    audience_meta = meta_result[0]

            # Deploy to platform
            platform_ad_id = await adapter.create_ad(
                campaign_id=platform_campaign_id,
                variant_code=variant_code,
                genome=genome,
                daily_budget=float(per_variant_budget),
                media_info=media_info,
                audience_meta=audience_meta,
            )

            # Insert deployment record
            deployment_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO deployments (id, variant_id, platform, platform_ad_id,
                                            daily_budget, is_active, created_at, updated_at)
                    VALUES (:id, :variant_id, :platform, :platform_ad_id,
                            :daily_budget, TRUE, NOW(), NOW())
                """),
                {
                    "id": deployment_id,
                    "variant_id": variant_id,
                    "platform": platform,
                    "platform_ad_id": platform_ad_id,
                    "daily_budget": per_variant_budget,
                },
            )

            # Activate variant
            await session.execute(
                text("""
                    UPDATE variants
                    SET status = 'active', deployed_at = NOW()
                    WHERE id = :id
                """),
                {"id": variant_id},
            )

            deployments.append(
                {
                    "variant_id": str(variant_id),
                    "variant_code": variant_code,
                    "platform_ad_id": platform_ad_id,
                    "daily_budget": float(per_variant_budget),
                }
            )

            logger.info(
                "Deployed approved variant %s (ad_id=%s) with budget %.2f",
                variant_code,
                platform_ad_id,
                per_variant_budget,
            )

        except Exception as exc:
            logger.warning(
                "Failed to deploy approved variant %s: %s",
                variant_code,
                exc,
            )

    await session.flush()
    return deployments
