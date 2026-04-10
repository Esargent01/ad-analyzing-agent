"""Test data factories for the ad creative agent system.

Plain-function factories (no factory_boy dependency required) that
produce valid domain objects for use in unit and integration tests.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from src.models.genome import GenomeSchema
from src.models.metrics import DailyRollup, MetricsSnapshot
from src.models.variant import VariantCreate, VariantResponse, VariantStatus

# ---------------------------------------------------------------------------
# Canonical gene-pool values (subset used by factories)
# ---------------------------------------------------------------------------

_HEADLINES = [
    "Limited time: 40% off today only",
    "Join 12,000+ happy customers",
    "What are you waiting for?",
    "The smarter choice for your team",
]

_SUBHEADS = [
    "Join 12,000+ happy customers",
    "As seen in Forbes and TechCrunch",
    "Rated 4.9/5 by verified users",
    "Setup takes less than 5 minutes",
]

_CTA_TEXTS = [
    "Get started free",
    "Claim my discount",
    "Start my free trial",
    "See it in action",
]

_MEDIA_ASSETS = [
    "placeholder_lifestyle",
    "placeholder_product",
]

_AUDIENCES = [
    "retargeting_30d",
    "retargeting_7d",
    "lookalike_1pct",
    "lookalike_5pct",
    "interest_based",
    "broad",
]


def build_genome(
    *,
    headline: str | None = None,
    subhead: str | None = None,
    cta_text: str | None = None,
    media_asset: str | None = None,
    audience: str | None = None,
    seed: int | None = None,
) -> dict[str, str]:
    """Build a valid genome dict, optionally overriding individual slots.

    Randomly samples from known gene-pool values for any slot not
    explicitly provided.
    """
    rng = random.Random(seed)
    return {
        "headline": headline or rng.choice(_HEADLINES),
        "subhead": subhead or rng.choice(_SUBHEADS),
        "cta_text": cta_text or rng.choice(_CTA_TEXTS),
        "media_asset": media_asset or rng.choice(_MEDIA_ASSETS),
        "audience": audience or rng.choice(_AUDIENCES),
    }


def build_genome_schema(
    *,
    seed: int | None = None,
    **overrides: str,
) -> GenomeSchema:
    """Build a validated GenomeSchema from random gene-pool values."""
    genome_dict = build_genome(seed=seed, **overrides)
    return GenomeSchema.model_validate(genome_dict)


def build_metrics(
    *,
    variant_id: uuid.UUID | None = None,
    deployment_id: uuid.UUID | None = None,
    impressions: int = 5000,
    clicks: int = 150,
    conversions: int = 15,
    spend: Decimal | None = None,
    recorded_at: datetime | None = None,
) -> MetricsSnapshot:
    """Build a MetricsSnapshot with sensible defaults."""
    return MetricsSnapshot(
        recorded_at=recorded_at or datetime.now(UTC),
        variant_id=variant_id or uuid.uuid4(),
        deployment_id=deployment_id or uuid.uuid4(),
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        spend=spend or Decimal("75.00"),
    )


def build_daily_rollup(
    *,
    day: date | None = None,
    variant_id: uuid.UUID | None = None,
    impressions: int = 5000,
    clicks: int = 150,
    conversions: int = 15,
    spend: Decimal | None = None,
) -> DailyRollup:
    """Build a DailyRollup with sensible defaults."""
    return DailyRollup(
        day=day or date.today(),
        variant_id=variant_id or uuid.uuid4(),
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        spend=spend or Decimal("75.00"),
    )


def build_variant_data(
    *,
    variant_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    variant_code: str = "V1",
    genome: dict[str, str] | None = None,
    status: VariantStatus = VariantStatus.ACTIVE,
    generation: int = 1,
    seed: int | None = None,
) -> VariantResponse:
    """Build a VariantResponse suitable for analyst/orchestrator tests."""
    return VariantResponse(
        id=variant_id or uuid.uuid4(),
        campaign_id=campaign_id or uuid.uuid4(),
        variant_code=variant_code,
        genome=genome or build_genome(seed=seed),
        status=status,
        generation=generation,
        parent_ids=[],
        hypothesis="Test hypothesis",
        created_at=datetime.now(UTC),
        deployed_at=None,
        paused_at=None,
        retired_at=None,
    )


def build_variant_create(
    *,
    campaign_id: uuid.UUID | None = None,
    genome: dict[str, str] | None = None,
    generation: int = 1,
    hypothesis: str | None = "Test hypothesis",
    seed: int | None = None,
) -> VariantCreate:
    """Build a VariantCreate payload."""
    return VariantCreate(
        campaign_id=campaign_id or uuid.uuid4(),
        genome=genome or build_genome(seed=seed),
        generation=generation,
        parent_ids=[],
        hypothesis=hypothesis,
    )
