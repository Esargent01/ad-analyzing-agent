"""Integration tests for the Phase D self-serve import flow.

These tests exercise ``src.services.campaign_import`` with the DB
layer + Meta adapter factory stubbed out. That keeps the suite
hermetic (no Postgres, no Meta SDK) while still covering the real
service logic — cap enforcement, duplicate-guard, gene-pool
seeding, variant/deployment creation, and the picker payload
shape.

The four scenarios the plan's acceptance criteria call out:

1. ``list_importable_campaigns`` returns the adapter's campaigns
   with ``already_imported`` flipped for anything this user has
   already brought in.
2. ``import_campaign`` creates Campaign + Variants + Deployments
   + seed gene pool rows on the happy path.
3. ``CampaignCapExceeded`` fires at the cap boundary.
4. ``CampaignAlreadyImported`` fires on a double-import.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.db.tables import (
    Campaign,
    Deployment,
    GenePoolEntry,
    Variant,
)


class _IterResult:
    """Stand-in for ``Result`` when the service just iterates the rows."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def __iter__(self):  # noqa: D401 — emulating SQLAlchemy Result
        return iter(self._rows)
from src.exceptions import (
    CampaignAlreadyImported,
    CampaignCapExceeded,
)
from src.models.campaigns import (
    CampaignImportOverrides,
    ImportableCampaignsResponse,
)
from src.services.campaign_import import (
    _extract_genome,
    _seed_gene_pool_entries,
    import_campaign,
    list_importable_campaigns,
)


def _stub_settings(
    max_campaigns_per_user: int = 5,
    max_concurrent_variants: int = 10,
    min_impressions: int = 1000,
) -> SimpleNamespace:
    """Build a settings stub with only the fields the service reads."""
    return SimpleNamespace(
        max_campaigns_per_user=max_campaigns_per_user,
        max_concurrent_variants=max_concurrent_variants,
        min_impressions=min_impressions,
    )


def _fake_meta_campaigns() -> list[dict[str, object]]:
    return [
        {
            "meta_campaign_id": "120200000000001",
            "name": "Spring Promo",
            "status": "ACTIVE",
            "daily_budget": 50.0,
            "created_time": None,
            "objective": "LINK_CLICKS",
        },
        {
            "meta_campaign_id": "120200000000002",
            "name": "Summer Promo",
            "status": "PAUSED",
            "daily_budget": None,
            "created_time": None,
            "objective": "CONVERSIONS",
        },
        {
            "meta_campaign_id": "120200000000003",
            "name": "Evergreen",
            "status": "ACTIVE",
            "daily_budget": 25.0,
            "created_time": None,
            "objective": "LINK_CLICKS",
        },
    ]


def _fake_campaign_ads() -> list[dict[str, object]]:
    return [
        {
            "ad_id": "600000001",
            "ad_name": "ad_1",
            "status": "ACTIVE",
            "adset_id": "500000001",
            "creative_id": "c1",
            "creative_name": "creative_1",
            "headline": "Save 40% today",
            "body": "Join 12,000 happy customers",
            "link_url": "https://example.com/a",
            "cta_type": "SHOP_NOW",
            "image_url": "https://img.example.com/1.jpg",
        },
        {
            "ad_id": "600000002",
            "ad_name": "ad_2",
            "status": "PAUSED",
            "adset_id": "500000001",
            "creative_id": "c2",
            "creative_name": "creative_2",
            "headline": "Limited time: 40% off",
            "body": "Join 12,000 happy customers",
            "link_url": "https://example.com/b",
            "cta_type": "LEARN_MORE",
            "image_url": "https://img.example.com/2.jpg",
        },
    ]


class TestExtractGenome:
    """Unit-style tests for the ad-to-genome helper."""

    def test_pulls_all_slots(self) -> None:
        ad = {
            "headline": "H",
            "body": "B",
            "cta_type": "SHOP_NOW",
            "image_url": "https://x/y.jpg",
        }
        genome = _extract_genome(ad)
        assert genome == {
            "headline": "H",
            "body": "B",
            "cta_text": "SHOP_NOW",
            "image_url": "https://x/y.jpg",
        }

    def test_drops_empty_slots(self) -> None:
        ad = {"headline": "H", "body": "", "cta_type": None, "image_url": "  "}
        genome = _extract_genome(ad)
        assert genome == {"headline": "H"}

    def test_completely_empty_ad(self) -> None:
        assert _extract_genome({}) == {}


class TestListImportableCampaigns:
    """The picker payload must decorate rows with the already-imported flag."""

    async def test_marks_already_imported_rows(self) -> None:
        user_id = uuid4()
        adapter = SimpleNamespace(
            list_campaigns=AsyncMock(return_value=_fake_meta_campaigns())
        )
        session = AsyncMock()

        with patch(
            "src.services.campaign_import.get_meta_adapter_for_user",
            new=AsyncMock(return_value=adapter),
        ), patch(
            "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
            new=AsyncMock(return_value={"120200000000002"}),
        ), patch(
            "src.services.campaign_import.count_active_campaigns_for_user",
            new=AsyncMock(return_value=2),
        ), patch(
            "src.services.campaign_import.get_settings",
            return_value=_stub_settings(),
        ):
            response = await list_importable_campaigns(session, user_id)

        assert isinstance(response, ImportableCampaignsResponse)
        assert response.quota_used == 2
        assert response.quota_max == 5
        assert len(response.importable) == 3

        by_id = {r.meta_campaign_id: r for r in response.importable}
        assert by_id["120200000000001"].already_imported is False
        assert by_id["120200000000002"].already_imported is True
        assert by_id["120200000000003"].already_imported is False
        assert by_id["120200000000001"].daily_budget == 50.0


class TestSeedGenePoolEntries:
    async def test_inserts_unique_and_skips_existing(self) -> None:
        """Only new (slot, value) pairs should hit the session.add path."""
        genomes = [
            {"headline": "H1", "body": "B1", "cta_text": "Shop"},
            {"headline": "H1", "body": "B2", "cta_text": "Learn"},
            {"image_url": "https://img/1.jpg"},
        ]

        # Pretend H1 already exists so the seeder must skip it.
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_IterResult([("headline", "H1")])
        )
        added: list[object] = []
        session.add = lambda obj: added.append(obj)
        session.flush = AsyncMock()

        created = await _seed_gene_pool_entries(session, genomes)

        # 5 candidates total: (headline,H1)(body,B1)(body,B2)
        # (cta_text,Shop)(cta_text,Learn)(image_url,...)
        # H1 already exists → 5 new rows.
        assert created == 5
        assert len(added) == 5
        assert all(isinstance(row, GenePoolEntry) for row in added)
        slots = {row.slot_name for row in added}  # type: ignore[attr-defined]
        assert slots == {"body", "cta_text", "image_url"}

    async def test_no_candidates_short_circuits(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.add = AsyncMock()
        created = await _seed_gene_pool_entries(session, [])
        assert created == 0
        session.execute.assert_not_called()


class TestImportCampaign:
    """End-to-end tests for a single-campaign import."""

    async def test_happy_path_creates_all_rows(self) -> None:
        user_id = uuid4()
        adapter = SimpleNamespace(
            list_campaigns=AsyncMock(return_value=_fake_meta_campaigns()),
            list_campaign_ads=AsyncMock(return_value=_fake_campaign_ads()),
        )

        session = AsyncMock()
        added: list[object] = []

        def _add(obj: object) -> None:
            # Emulate the ORM by assigning a fresh UUID on insert so
            # downstream variant/deployment inserts can reference it.
            if isinstance(obj, Campaign) and obj.id is None:
                obj.id = uuid4()
            if isinstance(obj, Variant) and obj.id is None:
                obj.id = uuid4()
            added.append(obj)

        session.add = _add
        session.flush = AsyncMock()
        # _seed_gene_pool_entries runs a single SELECT for existing
        # rows; return an empty iterator so everything is "new".
        session.execute = AsyncMock(return_value=_IterResult([]))

        with patch(
            "src.services.campaign_import.get_settings",
            return_value=_stub_settings(),
        ), patch(
            "src.services.campaign_import.count_active_campaigns_for_user",
            new=AsyncMock(return_value=0),
        ), patch(
            "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
            new=AsyncMock(return_value=set()),
        ), patch(
            "src.services.campaign_import.get_meta_adapter_for_user",
            new=AsyncMock(return_value=adapter),
        ):
            summary = await import_campaign(
                session,
                user_id,
                meta_campaign_id="120200000000001",
                overrides=CampaignImportOverrides(
                    daily_budget=Decimal("75.00"),
                    max_concurrent_variants=8,
                    confidence_threshold=Decimal("0.9"),
                ),
            )

        campaigns = [obj for obj in added if isinstance(obj, Campaign)]
        variants = [obj for obj in added if isinstance(obj, Variant)]
        deployments = [obj for obj in added if isinstance(obj, Deployment)]
        gene_pool_rows = [obj for obj in added if isinstance(obj, GenePoolEntry)]

        assert len(campaigns) == 1
        assert len(variants) == 2
        assert len(deployments) == 2

        campaign = campaigns[0]
        assert campaign.owner_user_id == user_id
        assert campaign.platform_campaign_id == "120200000000001"
        assert campaign.name == "Spring Promo"
        assert campaign.daily_budget == Decimal("75.00")
        assert campaign.max_concurrent_variants == 8
        assert campaign.confidence_threshold == Decimal("0.9")
        assert campaign.is_active is True

        variant_codes = sorted(v.variant_code for v in variants)
        assert variant_codes == ["V1", "V2"]
        for v in variants:
            assert v.generation == 0
            assert v.parent_ids == []
            assert "headline" in v.genome

        # Deployments mirror the ad statuses 1:1.
        is_active_flags = sorted(d.is_active for d in deployments)
        assert is_active_flags == [False, True]
        assert {d.platform_ad_id for d in deployments} == {"600000001", "600000002"}

        # Two unique headlines, 1 unique body, 2 unique CTAs, 2 unique images
        # → 7 new gene pool rows. summary.seeded_gene_pool_entries
        # and the collected rows must agree.
        assert summary.seeded_gene_pool_entries == len(gene_pool_rows) == 7
        assert summary.registered_deployments == 2
        assert summary.platform_campaign_id == "120200000000001"
        assert summary.daily_budget == Decimal("75.00")

    async def test_cap_exceeded_raises_before_meta_io(self) -> None:
        """The cap check must fire before any adapter is constructed."""
        user_id = uuid4()
        session = AsyncMock()

        # Adapter should NOT be touched on this path.
        adapter_factory = AsyncMock()

        with patch(
            "src.services.campaign_import.get_settings",
            return_value=_stub_settings(max_campaigns_per_user=5),
        ), patch(
            "src.services.campaign_import.count_active_campaigns_for_user",
            new=AsyncMock(return_value=5),
        ), patch(
            "src.services.campaign_import.get_meta_adapter_for_user",
            new=adapter_factory,
        ):
            with pytest.raises(CampaignCapExceeded) as excinfo:
                await import_campaign(
                    session, user_id, "120200000000001", overrides=None
                )

        assert excinfo.value.current == 5
        assert excinfo.value.maximum == 5
        adapter_factory.assert_not_awaited()

    async def test_duplicate_import_raises(self) -> None:
        user_id = uuid4()
        session = AsyncMock()

        with patch(
            "src.services.campaign_import.get_settings",
            return_value=_stub_settings(),
        ), patch(
            "src.services.campaign_import.count_active_campaigns_for_user",
            new=AsyncMock(return_value=1),
        ), patch(
            "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
            new=AsyncMock(return_value={"120200000000001"}),
        ):
            with pytest.raises(CampaignAlreadyImported, match="already imported"):
                await import_campaign(
                    session, user_id, "120200000000001", overrides=None
                )

    async def test_campaign_not_in_user_account_raises_value_error(self) -> None:
        """If Meta returns no match for the requested ID, bail clearly."""
        user_id = uuid4()
        adapter = SimpleNamespace(
            list_campaigns=AsyncMock(return_value=_fake_meta_campaigns()),
            list_campaign_ads=AsyncMock(return_value=[]),
        )
        session = AsyncMock()

        with patch(
            "src.services.campaign_import.get_settings",
            return_value=_stub_settings(),
        ), patch(
            "src.services.campaign_import.count_active_campaigns_for_user",
            new=AsyncMock(return_value=0),
        ), patch(
            "src.services.campaign_import.get_imported_meta_campaign_ids_for_user",
            new=AsyncMock(return_value=set()),
        ), patch(
            "src.services.campaign_import.get_meta_adapter_for_user",
            new=AsyncMock(return_value=adapter),
        ):
            with pytest.raises(ValueError, match="not found"):
                await import_campaign(
                    session, user_id, "not-a-real-id", overrides=None
                )
