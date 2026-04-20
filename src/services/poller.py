"""Metrics polling service.

Polls all active deployments for a campaign concurrently via
asyncio.gather(), persists metrics snapshots to the database,
and handles individual deployment failures gracefully.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time

from sqlalchemy import text
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

    # Objective-specific action counts (populated by the Meta adapter
    # from the ``actions`` array on Insights rows; zero elsewhere).
    leads: int = 0
    post_engagements: int = 0


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

    async def poll_campaign_for_date(
        self,
        campaign_id: uuid.UUID,
        report_date: date,
    ) -> list[MetricsSnapshot]:
        """Poll settled metrics for *report_date* for every active deployment.

        Unlike :meth:`poll_campaign`, which asks Meta for ``date_preset=today``
        (partial current-day data), this variant queries the platform with an
        explicit ``time_range`` covering ``report_date`` so the numbers are
        final/settled. Used by ``send-daily-reports`` so yesterday's spend
        actually lands in the aggregate before the report renders.

        Any existing metrics rows inside ``[report_date 00:00, report_date+1 00:00)``
        for the affected variants are deleted before the new settled
        snapshots are inserted. This prevents double-counting in
        ``_aggregate_metrics``'s SUM-based roll-up when an earlier
        partial-day poll already wrote a row for that window.

        Args:
            campaign_id: Campaign whose deployments to poll.
            report_date: The UTC date to fetch metrics for.

        Returns:
            List of successfully collected MetricsSnapshot objects, each
            stamped with ``collected_at = report_date 23:59:00 UTC`` so it
            falls cleanly inside the report's day window.
        """
        import asyncio

        deployments = await self._fetch_active_deployments(campaign_id)
        if not deployments:
            logger.info(
                "No active deployments for campaign %s — skipping %s backfill",
                campaign_id,
                report_date.isoformat(),
            )
            return []

        logger.info(
            "Polling %d deployments for campaign %s on %s (settled)",
            len(deployments),
            campaign_id,
            report_date.isoformat(),
        )

        since = report_date.isoformat()
        until = report_date.isoformat()
        stamp = datetime.combine(report_date, time(23, 59, 0), tzinfo=UTC)

        tasks = [self._poll_single_for_range(dep, (since, until), stamp) for dep in deployments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        snapshots: list[MetricsSnapshot] = []
        for dep, result in zip(deployments, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "Failed to poll deployment %s (ad_id=%s) for %s: %s",
                    dep.deployment_id,
                    dep.platform_ad_id,
                    report_date.isoformat(),
                    result,
                    exc_info=result,
                )
                continue
            snapshots.append(result)

        if snapshots:
            variant_ids = {snap.variant_id for snap in snapshots}
            await self._delete_snapshots_in_day(variant_ids, report_date)
            await self._save_snapshots(snapshots)
            logger.info(
                "Backfilled %d settled snapshots for campaign %s on %s",
                len(snapshots),
                campaign_id,
                report_date.isoformat(),
            )

        return snapshots

    async def _poll_single_for_range(
        self,
        deployment: _DeploymentInfo,
        time_range: tuple[str, str],
        stamp: datetime,
    ) -> MetricsSnapshot:
        """Poll a deployment for an explicit date range, stamping at *stamp*."""
        try:
            metrics: AdMetrics = await self._adapter.get_metrics(
                deployment.platform_ad_id,
                time_range=time_range,
            )
        except PlatformAPIError:
            raise
        except Exception as exc:
            raise PlatformAPIError(
                platform=deployment.platform,
                message=(
                    f"Unexpected error polling ad {deployment.platform_ad_id} "
                    f"for {time_range[0]}..{time_range[1]}: {exc}"
                ),
                response_body=None,
            ) from exc

        # Override ``collected_at`` so the row lands inside the report's
        # day window even though we polled after the fact.
        metrics = replace(metrics, collected_at=stamp)

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
            leads=metrics.leads,
            post_engagements=metrics.post_engagements,
        )

    async def _delete_snapshots_in_day(
        self,
        variant_ids: set[uuid.UUID],
        report_date: date,
    ) -> None:
        """Delete existing metrics rows for *variant_ids* within *report_date*.

        Prevents double-counting when the SUM-based ``_aggregate_metrics``
        query later rolls up the fresh settled snapshot alongside an older
        partial-day row from the optimization cycle poll.
        """
        if not variant_ids:
            return
        await self._session.execute(
            text(
                """
                DELETE FROM metrics
                WHERE variant_id = ANY(:ids)
                  AND recorded_at >= :day_start
                  AND recorded_at < :day_end
                """
            ),
            {
                "ids": list(variant_ids),
                "day_start": datetime.combine(report_date, time.min, tzinfo=UTC),
                "day_end": datetime.combine(
                    date.fromordinal(report_date.toordinal() + 1),
                    time.min,
                    tzinfo=UTC,
                ),
            },
        )

    async def _fetch_active_deployments(self, campaign_id: uuid.UUID) -> list[_DeploymentInfo]:
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
            leads=metrics.leads,
            post_engagements=metrics.post_engagements,
        )

    async def _save_snapshots(self, snapshots: list[MetricsSnapshot]) -> None:
        """Persist full-funnel metrics snapshots to the metrics hypertable."""
        insert_sql = text("""
            INSERT INTO metrics (
                recorded_at, variant_id, deployment_id,
                impressions, clicks, conversions, spend,
                reach, video_views_3s, video_views_15s, thruplays,
                link_clicks, landing_page_views, add_to_carts,
                purchases, purchase_value,
                leads, post_engagements
            ) VALUES (
                :recorded_at, :variant_id, :deployment_id,
                :impressions, :clicks, :conversions, :spend,
                :reach, :video_views_3s, :video_views_15s, :thruplays,
                :link_clicks, :landing_page_views, :add_to_carts,
                :purchases, :purchase_value,
                :leads, :post_engagements
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
                "leads": snap.leads,
                "post_engagements": snap.post_engagements,
            }
            for snap in snapshots
        ]

        for param in params:
            await self._session.execute(insert_sql, param)

        await self._session.flush()
