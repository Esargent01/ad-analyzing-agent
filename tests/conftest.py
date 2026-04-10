"""Shared test fixtures for the ad creative agent system."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.adapters.mock import MockAdapter
from src.models.genome import GenePool, GenomeSchema
from src.models.metrics import MetricsSnapshot

# Resolve paths relative to the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GENE_POOL_SEED_PATH = str(PROJECT_ROOT / "gene_pool_seed.json")


@pytest.fixture()
def gene_pool() -> GenePool:
    """Load the gene pool from the seed file."""
    return GenePool.from_file(GENE_POOL_SEED_PATH)


@pytest.fixture()
def sample_genome() -> GenomeSchema:
    """Return a valid GenomeSchema using known gene-pool values."""
    return GenomeSchema(
        headline="Limited time: 40% off today only",
        subhead="Join 12,000+ happy customers",
        cta_text="Get started free",
        media_asset="placeholder_lifestyle",
        audience="retargeting_30d",
    )


@pytest.fixture()
def mock_adapter() -> MockAdapter:
    """Return a MockAdapter with a deterministic seed."""
    return MockAdapter(seed=42)


@pytest.fixture()
def sample_metrics() -> list[MetricsSnapshot]:
    """Return a list of realistic MetricsSnapshot objects for testing."""
    variant_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    deployment_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    now = datetime.now(UTC)

    return [
        MetricsSnapshot(
            recorded_at=now,
            variant_id=variant_id,
            deployment_id=deployment_id,
            impressions=5000,
            clicks=150,
            conversions=15,
            spend=Decimal("75.00"),
        ),
        MetricsSnapshot(
            recorded_at=now,
            variant_id=variant_id,
            deployment_id=deployment_id,
            impressions=3000,
            clicks=60,
            conversions=6,
            spend=Decimal("30.00"),
        ),
        MetricsSnapshot(
            recorded_at=now,
            variant_id=variant_id,
            deployment_id=deployment_id,
            impressions=8000,
            clicks=400,
            conversions=40,
            spend=Decimal("200.00"),
        ),
    ]


@pytest.fixture()
def sample_genome_dict() -> dict[str, str]:
    """Return a valid genome as a plain dict."""
    return {
        "headline": "Limited time: 40% off today only",
        "subhead": "Join 12,000+ happy customers",
        "cta_text": "Get started free",
        "media_asset": "placeholder_lifestyle",
        "audience": "retargeting_30d",
    }
