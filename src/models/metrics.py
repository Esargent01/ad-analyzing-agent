"""Metrics Pydantic models for snapshots and daily rollups."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class MetricsSnapshot(BaseModel):
    """A single metrics snapshot polled from an ad platform."""

    model_config = ConfigDict(strict=True)

    recorded_at: datetime
    variant_id: UUID
    deployment_id: UUID
    impressions: int
    clicks: int
    conversions: int
    spend: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ctr(self) -> Decimal:
        """Click-through rate: clicks / impressions."""
        if self.impressions > 0:
            return Decimal(self.clicks) / Decimal(self.impressions)
        return Decimal(0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cpc(self) -> Decimal:
        """Cost per click: spend / clicks."""
        if self.clicks > 0:
            return self.spend / Decimal(self.clicks)
        return Decimal(0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cpa(self) -> Decimal:
        """Cost per acquisition: spend / conversions."""
        if self.conversions > 0:
            return self.spend / Decimal(self.conversions)
        return Decimal(0)


class DailyRollup(BaseModel):
    """Pre-aggregated daily metrics for a single variant."""

    model_config = ConfigDict(strict=True, from_attributes=True)

    day: date
    variant_id: UUID
    impressions: int
    clicks: int
    conversions: int
    spend: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ctr(self) -> Decimal:
        """Click-through rate for the day."""
        if self.impressions > 0:
            return Decimal(self.clicks) / Decimal(self.impressions)
        return Decimal(0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cpa(self) -> Decimal:
        """Cost per acquisition for the day."""
        if self.conversions > 0:
            return self.spend / Decimal(self.conversions)
        return Decimal(0)
