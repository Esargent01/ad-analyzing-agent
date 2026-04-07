"""Abstract base adapter for ad platform integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class AdMetrics:
    """Full-funnel metrics snapshot returned by platform adapters.

    Covers the complete performance marketing funnel:
    impressions -> reach -> video views (3s/15s/thruplay) ->
    link clicks -> landing page views -> add to carts ->
    purchases -> purchase value (ROAS).
    """

    # Core delivery metrics
    impressions: int
    clicks: int
    conversions: int
    spend: float

    # Extended funnel metrics
    reach: int = 0
    video_views_3s: int = 0
    video_views_15s: int = 0
    thruplays: int = 0
    link_clicks: int = 0
    landing_page_views: int = 0
    add_to_carts: int = 0
    purchases: int = 0
    purchase_value: float = 0.0

    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # -- Derived metrics (computed, not stored) --

    @property
    def frequency(self) -> float:
        """Average impressions per unique user."""
        if self.reach == 0:
            return 0.0
        return self.impressions / self.reach

    @property
    def cpm(self) -> float:
        """Cost per thousand impressions."""
        if self.impressions == 0:
            return 0.0
        return (self.spend / self.impressions) * 1000

    @property
    def hook_rate(self) -> float:
        """3-second video view rate (hook rate)."""
        if self.impressions == 0:
            return 0.0
        return self.video_views_3s / self.impressions

    @property
    def hold_rate(self) -> float:
        """15-second view rate relative to 3-second views."""
        if self.video_views_3s == 0:
            return 0.0
        return self.video_views_15s / self.video_views_3s

    @property
    def ctr(self) -> float:
        """Click-through rate as a decimal."""
        if self.impressions == 0:
            return 0.0
        return self.clicks / self.impressions

    @property
    def cpc(self) -> float:
        """Cost per click."""
        if self.clicks == 0:
            return 0.0
        return self.spend / self.clicks

    @property
    def cpa(self) -> float:
        """Cost per acquisition / conversion."""
        if self.conversions == 0:
            return 0.0
        return self.spend / self.conversions

    @property
    def cost_per_purchase(self) -> float:
        """Cost per purchase."""
        if self.purchases == 0:
            return 0.0
        return self.spend / self.purchases

    @property
    def roas(self) -> float:
        """Return on ad spend."""
        if self.spend == 0:
            return 0.0
        return self.purchase_value / self.spend


@dataclass(frozen=True)
class MediaAsset:
    """A media asset (image or video) from the platform's library."""

    asset_type: str  # "image" or "video"
    platform_id: str  # image hash or video ID
    name: str
    thumbnail_url: str = ""
    source_url: str = ""
    width: int = 0
    height: int = 0
    duration_secs: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


class BaseAdapter(ABC):
    """Abstract interface for ad platform adapters.

    All platform-specific adapters must implement this interface.
    Every method is async. Implementations must raise
    ``PlatformAPIError`` on platform-level failures and include
    the response body for debugging.
    """

    @abstractmethod
    async def create_ad(
        self,
        campaign_id: str,
        variant_code: str,
        genome: dict[str, str],
        daily_budget: float,
        media_info: dict[str, str] | None = None,
    ) -> str:
        """Create an ad on the platform from a creative genome.

        Args:
            campaign_id: Platform-side campaign ID to attach the ad to.
            variant_code: Human-readable code like ``V12``.
            genome: Genome dict mapping slot names to slot values.
            daily_budget: Daily spend cap in the campaign currency.
            media_info: Optional dict with ``asset_type`` ("image"/"video")
                and ``platform_id`` to use a real media asset.

        Returns:
            The platform-native ad ID (e.g. Meta ad ID, Google ad resource name).
        """

    @abstractmethod
    async def pause_ad(self, platform_ad_id: str) -> bool:
        """Pause a running ad.

        Returns:
            ``True`` if the ad was successfully paused.
        """

    @abstractmethod
    async def resume_ad(self, platform_ad_id: str) -> bool:
        """Resume a paused ad.

        Returns:
            ``True`` if the ad was successfully resumed.
        """

    @abstractmethod
    async def update_budget(self, platform_ad_id: str, new_budget: float) -> bool:
        """Update the daily budget for an ad.

        Args:
            platform_ad_id: Platform-native ad ID.
            new_budget: New daily budget amount.

        Returns:
            ``True`` if the budget was successfully updated.
        """

    @abstractmethod
    async def get_metrics(self, platform_ad_id: str) -> AdMetrics:
        """Fetch the latest metrics for an ad.

        Returns:
            An ``AdMetrics`` dataclass with impressions, clicks, conversions, spend.
        """

    @abstractmethod
    async def delete_ad(self, platform_ad_id: str) -> bool:
        """Delete an ad from the platform.

        Returns:
            ``True`` if the ad was successfully deleted.
        """

    async def list_media_library(
        self, asset_type: str = "all",
    ) -> list[MediaAsset]:
        """List media assets (images/videos) from the platform's library.

        Args:
            asset_type: Filter by ``"image"``, ``"video"``, or ``"all"``.

        Returns:
            List of ``MediaAsset`` objects with platform IDs and metadata.

        Note:
            Not abstract — default returns empty list for platforms
            that don't support media library browsing.
        """
        return []
