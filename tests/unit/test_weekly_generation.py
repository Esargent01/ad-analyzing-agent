"""Tests for run_weekly_generation and load_proposed_variants."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.generator import GenomeWithHypothesis
from src.exceptions import LLMError
from src.models.genome import GenePool
from src.services.weekly import (
    _summarize_genome,
    load_proposed_variants,
    run_weekly_generation,
)


def _valid_genome() -> dict[str, str]:
    return {
        "headline": "Limited time: 40% off today only",
        "subhead": "Join 12,000+ happy customers",
        "cta_text": "Get started free",
        "media_asset": "placeholder_lifestyle",
        "audience": "retargeting_30d",
    }


def _make_settings() -> SimpleNamespace:
    return SimpleNamespace(
        anthropic_api_key="sk-test",
        anthropic_model="claude-sonnet-4",
        proposal_ttl_days=14,
    )


def _make_session(
    *,
    max_variants: int = 10,
    active_count: int = 2,
    pending_count: int = 0,
    max_generation: int = 3,
    existing_genomes: list[dict[str, str]] | None = None,
    campaign_found: bool = True,
) -> AsyncMock:
    """Build a mock AsyncSession with stubbed .execute() results.

    The mock returns a sequence of results matching the SQL calls in
    ``run_weekly_generation``. The order must match the function body.
    """
    session = AsyncMock()
    session.flush = AsyncMock()

    existing_rows = [(g,) for g in (existing_genomes or [])]

    # Sequenced results for each session.execute(...) call.
    # Order must match the source of run_weekly_generation.
    call_results: list[MagicMock] = []

    # 1) max_concurrent_variants lookup
    max_res = MagicMock()
    max_res.fetchone.return_value = (max_variants,) if campaign_found else None
    call_results.append(max_res)

    # 2) active variant count
    active_res = MagicMock()
    active_res.scalar_one.return_value = active_count
    call_results.append(active_res)

    # 3) pending approval count
    pending_res = MagicMock()
    pending_res.scalar_one.return_value = pending_count
    call_results.append(pending_res)

    # 4) existing (non-retired) genomes
    existing_res = MagicMock()
    existing_res.fetchall.return_value = existing_rows
    call_results.append(existing_res)

    # 5) current max generation
    gen_res = MagicMock()
    gen_res.scalar_one.return_value = max_generation
    call_results.append(gen_res)

    # For each variant insert we need: next_variant_code, insert variant,
    # insert approval_queue. The MagicMock for next_variant_code returns
    # the code; the two inserts just need to not raise.
    def _make_code_result(code: str) -> MagicMock:
        r = MagicMock()
        r.scalar_one.return_value = code
        return r

    # Return code results on demand — we'll append as needed via side_effect
    queued_codes = ["V9", "V10", "V11", "V12", "V13"]
    insert_responses: list[MagicMock] = []
    for code in queued_codes:
        insert_responses.append(_make_code_result(code))  # next_variant_code
        insert_responses.append(MagicMock())  # INSERT variants
        insert_responses.append(MagicMock())  # INSERT approval_queue

    async def _execute(*args, **kwargs):  # noqa: ANN001
        if call_results:
            return call_results.pop(0)
        if insert_responses:
            return insert_responses.pop(0)
        return MagicMock()

    session.execute = AsyncMock(side_effect=_execute)
    return session


@pytest.fixture()
def mock_gene_pool() -> GenePool:
    """Return a minimal gene pool that matches _valid_genome()."""
    return GenePool.model_validate(
        {
            "headline": [{"value": "Limited time: 40% off today only", "description": ""}],
            "subhead": [{"value": "Join 12,000+ happy customers", "description": ""}],
            "cta_text": [{"value": "Get started free", "description": ""}],
            "media_asset": [{"value": "placeholder_lifestyle", "description": ""}],
            "audience": [{"value": "retargeting_30d", "description": ""}],
        }
    )


class TestSummarizeGenome:
    def test_summary_contains_headline_cta_audience(self) -> None:
        summary = _summarize_genome(
            {
                "headline": "Save 40%",
                "cta_text": "Buy now",
                "audience": "retargeting",
                "subhead": "ignored",
            }
        )
        assert "Save 40%" in summary
        assert "Buy now" in summary
        assert "retargeting" in summary

    def test_summary_truncates_long_headline(self) -> None:
        long_headline = "This headline is intentionally way too long to fit anywhere cleanly"
        summary = _summarize_genome({"headline": long_headline, "cta_text": "Go"})
        assert "..." in summary

    def test_summary_handles_empty_genome(self) -> None:
        assert _summarize_genome({}) == "—"


class TestRunWeeklyGeneration:
    """Tests for run_weekly_generation capacity logic."""

    @pytest.mark.asyncio
    async def test_returns_early_when_campaign_missing(self) -> None:
        campaign_id = uuid.uuid4()
        session = AsyncMock()
        session.flush = AsyncMock()

        missing_res = MagicMock()
        missing_res.fetchone.return_value = None
        session.execute = AsyncMock(return_value=missing_res)

        with patch(
            "src.services.weekly.expire_stale_proposals",
            new=AsyncMock(return_value=0),
        ):
            with patch("src.services.weekly.get_settings", return_value=_make_settings()):
                expired, paused = await run_weekly_generation(session, campaign_id)

        assert expired == 0
        assert paused is False

    @pytest.mark.asyncio
    async def test_generation_paused_when_queue_full(self, mock_gene_pool: GenePool) -> None:
        """When active + pending >= max, generation is paused."""
        campaign_id = uuid.uuid4()
        session = _make_session(max_variants=10, active_count=6, pending_count=4)

        with (
            patch("src.services.weekly.get_settings", return_value=_make_settings()),
            patch(
                "src.services.weekly.expire_stale_proposals",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.services.weekly._load_gene_pool",
                new=AsyncMock(return_value=mock_gene_pool),
            ),
        ):
            expired, paused = await run_weekly_generation(session, campaign_id)

        assert expired == 0
        assert paused is True

    @pytest.mark.asyncio
    async def test_expired_count_bubbles_up_with_paused(self, mock_gene_pool: GenePool) -> None:
        """expire_stale_proposals count is returned even when paused."""
        campaign_id = uuid.uuid4()
        session = _make_session(max_variants=5, active_count=3, pending_count=2)

        with (
            patch("src.services.weekly.get_settings", return_value=_make_settings()),
            patch(
                "src.services.weekly.expire_stale_proposals",
                new=AsyncMock(return_value=2),
            ),
            patch(
                "src.services.weekly._load_gene_pool",
                new=AsyncMock(return_value=mock_gene_pool),
            ),
        ):
            expired, paused = await run_weekly_generation(session, campaign_id)

        assert expired == 2
        assert paused is True

    @pytest.mark.asyncio
    async def test_generation_capped_at_three(self, mock_gene_pool: GenePool) -> None:
        """Per-week generation is capped at 3 regardless of slots available."""
        campaign_id = uuid.uuid4()
        session = _make_session(max_variants=20, active_count=0, pending_count=0)

        fake_generator = AsyncMock()
        fake_generator.generate_variants = AsyncMock(
            return_value=[
                GenomeWithHypothesis(genome=_valid_genome(), hypothesis="h1"),
                GenomeWithHypothesis(genome=_valid_genome(), hypothesis="h2"),
                GenomeWithHypothesis(genome=_valid_genome(), hypothesis="h3"),
            ]
        )

        with (
            patch("src.services.weekly.get_settings", return_value=_make_settings()),
            patch(
                "src.services.weekly.expire_stale_proposals",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.services.weekly._load_gene_pool",
                new=AsyncMock(return_value=mock_gene_pool),
            ),
            patch(
                "src.services.weekly.get_element_rankings",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "src.services.weekly.get_top_interactions",
                new=AsyncMock(return_value=[]),
            ),
            patch("src.services.weekly.anthropic"),
            patch(
                "src.services.weekly.GeneratorAgent",
                return_value=fake_generator,
            ),
        ):
            expired, paused = await run_weekly_generation(session, campaign_id)

        # Check the cap: generator was asked for 3, not 20
        fake_generator.generate_variants.assert_awaited_once()
        call_kwargs = fake_generator.generate_variants.call_args.kwargs
        assert call_kwargs["max_new"] == 3
        assert expired == 0
        assert paused is False

    @pytest.mark.asyncio
    async def test_llm_error_returns_gracefully(self, mock_gene_pool: GenePool) -> None:
        """LLMError from the generator is swallowed; function returns paused=False."""
        campaign_id = uuid.uuid4()
        session = _make_session(max_variants=10, active_count=0, pending_count=0)

        fake_generator = AsyncMock()
        fake_generator.generate_variants = AsyncMock(side_effect=LLMError("nothing usable"))

        with (
            patch("src.services.weekly.get_settings", return_value=_make_settings()),
            patch(
                "src.services.weekly.expire_stale_proposals",
                new=AsyncMock(return_value=1),
            ),
            patch(
                "src.services.weekly._load_gene_pool",
                new=AsyncMock(return_value=mock_gene_pool),
            ),
            patch(
                "src.services.weekly.get_element_rankings",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "src.services.weekly.get_top_interactions",
                new=AsyncMock(return_value=[]),
            ),
            patch("src.services.weekly.anthropic"),
            patch(
                "src.services.weekly.GeneratorAgent",
                return_value=fake_generator,
            ),
        ):
            expired, paused = await run_weekly_generation(session, campaign_id)

        assert expired == 1
        assert paused is False


class TestLoadProposedVariants:
    """Tests for load_proposed_variants classification and sorting."""

    @pytest.mark.asyncio
    async def test_empty_pending_returns_empty_list(self) -> None:
        campaign_id = uuid.uuid4()
        session = AsyncMock()

        with (
            patch("src.services.weekly.get_settings", return_value=_make_settings()),
            patch(
                "src.services.weekly.get_pending_approvals",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await load_proposed_variants(session, campaign_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_classifies_fresh_as_new_and_old_as_expiring(self) -> None:
        campaign_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        v_new = uuid.uuid4()
        v_old = uuid.uuid4()

        pending = [
            SimpleNamespace(
                id=uuid.uuid4(),
                variant_id=v_new,
                submitted_at=now - timedelta(days=2),
                genome_snapshot=_valid_genome(),
                hypothesis="recent",
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                variant_id=v_old,
                submitted_at=now - timedelta(days=10),
                genome_snapshot=_valid_genome(),
                hypothesis="stale",
            ),
        ]

        code_rows = MagicMock()
        code_rows.fetchall.return_value = [
            (v_new, "V12"),
            (v_old, "V5"),
        ]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=code_rows)

        with (
            patch("src.services.weekly.get_settings", return_value=_make_settings()),
            patch(
                "src.services.weekly.get_pending_approvals",
                new=AsyncMock(return_value=pending),
            ),
        ):
            result = await load_proposed_variants(session, campaign_id)

        assert len(result) == 2
        # Expiring should be sorted first
        assert result[0].classification == "expiring_soon"
        assert result[0].variant_code == "V5"
        assert result[1].classification == "new"
        assert result[1].variant_code == "V12"
        # days_until_expiry sanity: stale one < fresh one
        assert result[0].days_until_expiry < result[1].days_until_expiry
