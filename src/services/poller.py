"""Metrics polling service.

Polls all active deployments for a campaign concurrently via
asyncio.gather(), persists metrics snapshots to the database,
and handles individual deployment failures gracefully.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.base import AdMetrics, BaseAdapter
from src.exceptions import PlatformAPIError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricsSnapshot:
    """A full-funnel metrics snapshot ready for database persistence.

    Covers the complete performance marketing funnel from impressions
    through purchases and ROAS.
    """

    variant_id: uuid.UUID
    deployment_id: uuid.UUID
    collected_at: datetime

    # Core delivery
    impressions: int
    clicks: int
    conversions: int
    spend: float

    # Extended funnel
    reach: int = 0
    video_views_3s: int = 0
    video_views_15s: int = 0
    thruplays: int = 0
    link_clicks: int = 0
    landing_page_views: int = 0
    add_to_carts: int = 0
    purchases: int = 0
    purchase_value: float = 0.0


@dataclass(frozen=True)
class _DeploymentInfo:
    """Internal struct for deployment data fetched from the database."""

    deployment_id: uuid.UUID
    variant_id: uuid.UUID
    platform_ad_id: str
    platform: str


class MetricsPoller:
    """Polls ad platform metrics for all active deployments in a campaign.

    Args:
        adapter: The ad platform adapter used to fetch metrics.
        session: An async SQLAlchemy session for database operations.
    """

    def __init__(self, adapter: BaseAdapter, session: AsyncSession) -> None:
        self._adapter = adapter
        self._session = session

    async def poll_campaign(self, campaign_id: uuid.UUID) -> list[MetricsSnapshot]:
        """Poll metrics for all active deployments in a campaign.

        Fetches metrics concurrently using asyncio.gather(). Individual
        deployment failures are logged but do not stop polling of
        other deployments.

        Args:
            campaign_id: The campaign whose deployments to poll.

        Returns:
            List of successfully collected MetricsSnapshot objects.
        """
        import asyncio

        deployments = await self._fetch_active_deployments(campaign_id)
        if not deployments:
            logger.info("No active deployments for campaign %s", campaign_id)
            return []

        logger.info(
            "Polling %d active deployments for campaign %s",
            len(deployments),
            campaign_id,
        )

        # Poll all deployments concurrently; return_exceptions=True ensures
        # one failure doesn't cancel the others.
        tasks = [self._poll_single(dep) for dep in deployments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        snapshots: list[MetricsSnapshot] = []
        for dep, result in zip(deployments, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Failed to poll deployment %s (ad_id=%s): %s",
                    dep.deployment_id,
                    dep.platform_ad_id,
                    result,
                    exc_info=result,
                )
                continue
            snapshots.append(result)

        # Persist all successful snapshots in one batch
        if snapshots:
            await self._save_snapshots(snapshots)
            logger.info(
                "Saved %d metrics snapshots for campaign %s",
                len(snapshots),
                campaign_id,
            )

        return snapshots

    async def _fetch_active_deployments(
        self, campaign_id: uuid.UUID
    ) -> list[_DeploymentInfo]:
        """Query active deployments for a campaign."""
        query = text("""
            SELECT d.id, d.variant_id, d.platform_ad_id, d.platform
            FROM deployments d
            JOIN variants v ON v.id = d.variant_id
            WHERE v.campaign_id = :campaign_id
              AND v.status = 'active'
              AND d.is_active = TRUE
        """)
        result = await self._session.execute(query, {"campaign_id": campaign_id})
        rows = result.fetchall()

        return [
            _DeploymentInfo(
                deployment_id=row[0],
                variant_id=row[1],
                platform_ad_id=row[2],
                platform=row[3],
            )
            for row in rows
        ]

    async def _poll_single(self, deployment: _DeploymentInfo) -> MetricsSnapshot:
        """Poll a single deployment and return a MetricsSnapshot.

        Raises:
            PlatformAPIError: If the platform adapter fails.
        """
        try:
            metrics: AdMetrics = await self._adapter.get_metrics(deployment.platform_ad_id)
        except PlatformAPIError:
            raise
        except Exception as exc:
            raise PlatformAPIError(
                platform=deployment.platform,
                message=f"Unexpected error polling ad {deployment.platform_ad_id}: {exc}",
                response_body=None,
            ) from exc

        return MetricsSnapshot(
            variant_id=deployment.variant_id,
            deployment_id=deployment.deployment_id,
            collected_at=metrics.collected_at,
            impressions=metrics.impressions,
            clicks=metrics.clicks,
            conversions=metrics.conversions,
            spend=metrics.spend,
            reach=metrics.reach,
            video_views_3s=metrics.video_views_3s,
            video_views_15s=metrics.video_views_15s,
            thruplays=metrics.thruplays,
            link_clicks=metrics.link_clicks,
            landing_page_views=metrics.landing_page_views,
            add_to_carts=metrics.add_to_carts,
            purchases=metrics.purchases,
            purchase_value=metrics.purchase_value,
        )

    async def _save_snapshots(self, snapshots: list[MetricsSnapshot]) -> None:
        """Persist full-funnel metrics snapshots to the metrics hypertable."""
        insert_sql = text("""
            INSERT INTO metrics (
                recorded_at, variant_id, deployment_id,
                impressions, clicks, conversions, spend,
                reach, video_views_3s, video_views_15s, thruplays,
                link_clicks, landing_page_views, add_to_carts,
                purchases, purchase_value
            ) VALUES (
                :recorded_at, :variant_id, :deployment_id,
                :impressions, :clicks, :conversions, :spend,
                :reach, :video_views_3s, :video_views_15s, :thruplays,
                :link_clicks, :landing_page_views, :add_to_carts,
                :purchases, :purchase_value
            )
        """)

        params = [
            {
                "recorded_at": snap.collected_at,
                "variant_id": snap.variant_id,
                "deployment_id": snap.deployment_id,
                "impressions": snap.impressions,
                "clicks": snap.clicks,
                "conversions": snap.conversions,
                "spend": snap.spend,
                "reach": snap.reach,
                "video_views_3s": snap.video_views_3s,
                "video_views_15s": snap.video_views_15s,
                "thruplays": snap.thruplays,
                "link_clicks": snap.link_clicks,
                "landing_page_views": snap.landing_page_views,
                "add_to_carts": snap.add_to_carts,
                "purchases": snap.purchases,
                "purchase_value": snap.purchase_value,
            }
            for snap in snapshots
        ]

        for param in params:
            await self._session.execute(insert_sql, param)

        await self._session.flush()
