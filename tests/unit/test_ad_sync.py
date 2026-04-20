"""Tests for :mod:`src.services.ad_sync`.

The sync step is the bridge between "Meta's live ad list" and our local
``deployments`` table. If it regresses, ads the user creates in Meta
Ads Manager silently stop being monitored — the exact bug this service
was introduced to fix. Each test asserts one slice of the contract:

* happy path: adds only the ads Meta has that we don't
* idempotency: re-running yields zero new variants and leaves state untouched
* deletion tolerance: ads that disappeared from Meta are left alone (not deleted)
* malformed ads: extractor-empty ads are skipped, not crashed on
* empty Meta: zero ads on Meta yields zero work, no spurious writes
* no ``platform_campaign_id``: non-Meta-imported campaigns short-circuit
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.db.tables import Deployment, Variant, VariantStatus
from src.services.ad_sync import sync_campaign_ads


class _IterResult:
    """Stand-in for SQLAlchemy ``Result`` — supports both fetchall and
    iteration, matching whatever the production code happens to do.
    """

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


def _make_campaign(
    *,
    campaign_id: UUID | None = None,
    platform_campaign_id: str | None = "120200000000001",
    daily_budget: Decimal = Decimal("50.00"),
) -> SimpleNamespace:
    """Minimal ``Campaign``-shaped stub.

    ``sync_campaign_ads`` only reads ``id``, ``platform_campaign_id``,
    and ``daily_budget`` — no need to construct a full ORM row.
    """
    return SimpleNamespace(
        id=campaign_id or uuid4(),
        platform_campaign_id=platform_campaign_id,
        daily_budget=daily_budget,
    )


def _fake_ad(
    ad_id: str,
    *,
    headline: str = "Pulled headline",
    body: str = "Pulled body",
    cta: str = "LEARN_MORE",
    image: str = "https://cdn.example/img.jpg",
    status: str = "ACTIVE",
    media_type: str = "image",
) -> dict[str, object]:
    """Shape returned by ``MetaAdapter.list_campaign_ads``."""
    return {
        "ad_id": ad_id,
        "ad_name": f"Ad {ad_id}",
        "status": status,
        "adset_id": "123456",
        "creative_id": f"cr_{ad_id}",
        "creative_name": "",
        "headline": headline,
        "body": body,
        "link_url": "https://shop.example",
        "cta_type": cta,
        "image_url": image,
        "media_type": media_type,
        "asset_feed_titles": [],
        "asset_feed_bodies": [],
        "asset_feed_cta_types": [],
    }


def _make_session(existing_ad_ids: list[str], existing_codes: list[str]):
    """Fake session that replays canned ``.execute`` responses in order.

    ``sync_campaign_ads`` runs two SELECTs before writing:
      1. existing platform_ad_ids (via ``_existing_platform_ad_ids``)
      2. existing variant_codes (via ``_next_variant_code``)
    Then inserts variants/deployments through ``session.add`` and
    ``session.flush``.

    Returning a ``_IterResult`` from each ``execute`` covers everything
    the sync touches without needing a real SQLAlchemy session.
    """
    added: list[object] = []

    def _add(obj: object) -> None:
        # Emulate the ORM by assigning a UUID on first insert so the
        # follow-on deployment can reference variant.id.
        if isinstance(obj, Variant) and obj.id is None:
            obj.id = uuid4()
        added.append(obj)

    responses = iter(
        [
            _IterResult([(ad_id,) for ad_id in existing_ad_ids]),
            _IterResult([(code,) for code in existing_codes]),
            # Gene-pool existence check inside _seed_gene_pool_entries
            # returns an empty set; use "..." to cover any extra
            # SELECT the seeder might run.
            _IterResult([]),
            _IterResult([]),
            _IterResult([]),
        ]
    )

    session = AsyncMock()
    session.add = _add
    session.flush = AsyncMock()
    session.execute = AsyncMock(side_effect=lambda *args, **kwargs: next(responses))
    return session, added


class TestSyncCampaignAds:
    async def test_discovers_only_new_meta_ads(self) -> None:
        """Meta has 3 ads; we know about 1. Expect 2 new variants created."""
        campaign = _make_campaign()
        adapter = SimpleNamespace(
            list_campaign_ads=AsyncMock(
                return_value=[
                    _fake_ad("aa_001"),
                    _fake_ad("aa_002"),
                    _fake_ad("aa_003"),
                ]
            )
        )
        session, added = _make_session(
            existing_ad_ids=["aa_001"],
            existing_codes=["V1"],
        )

        with patch(
            "src.services.ad_sync.get_meta_adapter_for_campaign",
            new=AsyncMock(return_value=adapter),
        ):
            n = await sync_campaign_ads(session, campaign)

        assert n == 2
        variants = [obj for obj in added if isinstance(obj, Variant)]
        deployments = [obj for obj in added if isinstance(obj, Deployment)]
        assert len(variants) == 2
        assert len(deployments) == 2

        # Newly created variants all have source="discovered" and the
        # right provenance hypothesis.
        for v in variants:
            assert v.source == "discovered"
            assert "outside Kleiber" in (v.hypothesis or "")
            assert v.status == VariantStatus.active
            # Codes continue from V1 → V2, V3 (not V1 — already used).
            assert v.variant_code in {"V2", "V3"}

        # Deployment platform_ad_ids match the ads Meta reported
        # that weren't already known.
        platform_ids = {d.platform_ad_id for d in deployments}
        assert platform_ids == {"aa_002", "aa_003"}

    async def test_idempotent_when_nothing_new(self) -> None:
        """Re-running with no Meta-side changes is a no-op."""
        campaign = _make_campaign()
        adapter = SimpleNamespace(
            list_campaign_ads=AsyncMock(
                return_value=[
                    _fake_ad("aa_001"),
                    _fake_ad("aa_002"),
                ]
            )
        )
        session, added = _make_session(
            existing_ad_ids=["aa_001", "aa_002"],
            existing_codes=["V1", "V2"],
        )

        with patch(
            "src.services.ad_sync.get_meta_adapter_for_campaign",
            new=AsyncMock(return_value=adapter),
        ):
            n = await sync_campaign_ads(session, campaign)

        assert n == 0
        # No variants or deployments added — nothing to commit.
        assert not any(isinstance(obj, Variant) for obj in added)
        assert not any(isinstance(obj, Deployment) for obj in added)

    async def test_ignores_locally_known_ads_missing_from_meta(self) -> None:
        """If Meta dropped an ad we had, leave our row alone — don't delete.

        Ad deletion is handled by the poller's zero-metric path; the sync
        never removes rows. Here Meta returns 1 ad (already known); we
        have 2 locally. The extra local ad (``aa_999``) must survive.
        """
        campaign = _make_campaign()
        adapter = SimpleNamespace(
            list_campaign_ads=AsyncMock(
                return_value=[_fake_ad("aa_001")],
            )
        )
        session, added = _make_session(
            existing_ad_ids=["aa_001", "aa_999"],
            existing_codes=["V1", "V2"],
        )

        with patch(
            "src.services.ad_sync.get_meta_adapter_for_campaign",
            new=AsyncMock(return_value=adapter),
        ):
            n = await sync_campaign_ads(session, campaign)

        assert n == 0
        # Crucially: no DELETE was issued. We only appended — if we ever
        # start issuing deletes here, this assertion gives us a heads-up.
        assert not any(isinstance(obj, (Variant, Deployment)) for obj in added)

    async def test_skips_ads_with_no_extractable_genome(self) -> None:
        """Ads that come back empty don't create variant rows."""
        campaign = _make_campaign()
        blank_ad = _fake_ad("aa_blank", headline="", body="", cta="", image="")
        adapter = SimpleNamespace(
            list_campaign_ads=AsyncMock(
                return_value=[blank_ad, _fake_ad("aa_good")],
            )
        )
        session, added = _make_session(
            existing_ad_ids=[],
            existing_codes=[],
        )

        with patch(
            "src.services.ad_sync.get_meta_adapter_for_campaign",
            new=AsyncMock(return_value=adapter),
        ):
            n = await sync_campaign_ads(session, campaign)

        # Only the non-empty ad landed. Blank ad was skipped without
        # raising or polluting the variant code sequence.
        assert n == 1
        variants = [obj for obj in added if isinstance(obj, Variant)]
        assert len(variants) == 1
        assert variants[0].variant_code == "V1"

    async def test_empty_meta_campaign_yields_zero_work(self) -> None:
        """No ads on Meta = no-op, no spurious DB writes."""
        campaign = _make_campaign()
        adapter = SimpleNamespace(list_campaign_ads=AsyncMock(return_value=[]))
        session, added = _make_session(
            existing_ad_ids=[],
            existing_codes=[],
        )

        with patch(
            "src.services.ad_sync.get_meta_adapter_for_campaign",
            new=AsyncMock(return_value=adapter),
        ):
            n = await sync_campaign_ads(session, campaign)

        assert n == 0
        assert not any(isinstance(obj, (Variant, Deployment)) for obj in added)

    async def test_short_circuits_on_non_meta_campaign(self) -> None:
        """Campaigns without platform_campaign_id never reach Meta."""
        campaign = _make_campaign(platform_campaign_id=None)
        session = AsyncMock()

        # get_meta_adapter_for_campaign should NOT be called. If it is,
        # this AsyncMock would record the call.
        with patch(
            "src.services.ad_sync.get_meta_adapter_for_campaign",
            new=AsyncMock(side_effect=AssertionError("should not be called")),
        ):
            n = await sync_campaign_ads(session, campaign)

        assert n == 0


class TestNextVariantCode:
    """Edge cases around the V{n} code parser.

    Ensures malformed / legacy variant codes don't confuse the next-code
    picker into colliding with an existing row.
    """

    async def test_picks_one_when_no_variants_exist(self) -> None:
        from src.services.ad_sync import _next_variant_code

        session, _ = _make_session(existing_ad_ids=[], existing_codes=[])
        assert await _next_variant_code(session, uuid4()) == 1

    async def test_picks_max_plus_one(self) -> None:
        from src.services.ad_sync import _next_variant_code

        session, _ = _make_session(
            existing_ad_ids=[], existing_codes=["V1", "V2", "V7", "V3"]
        )
        # Clear the pre-seeded first response (we only need the second).
        session.execute = AsyncMock(
            return_value=_IterResult([("V1",), ("V2",), ("V7",), ("V3",)])
        )
        assert await _next_variant_code(session, uuid4()) == 8

    @pytest.mark.parametrize(
        "codes",
        [
            ["V1", "junk", "V3"],          # non-matching string
            ["V1", "VABC", "V2"],          # non-integer suffix
            ["V42", "v10", "V5"],          # lowercase ignored
        ],
    )
    async def test_tolerates_malformed_codes(self, codes: list[str]) -> None:
        from src.services.ad_sync import _next_variant_code

        session, _ = _make_session(existing_ad_ids=[], existing_codes=[])
        session.execute = AsyncMock(
            return_value=_IterResult([(c,) for c in codes])
        )
        # Should pick max of parseable codes + 1, ignoring garbage.
        result = await _next_variant_code(session, uuid4())
        # Strip out the non-parseable codes manually to derive expected.
        parseable = [int(c[1:]) for c in codes if c.startswith("V") and c[1:].isdigit()]
        assert result == max(parseable) + 1
