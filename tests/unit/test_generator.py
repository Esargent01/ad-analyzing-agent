"""Tests for the LLM-powered GeneratorAgent with mocked Anthropic client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.generator import GeneratorAgent, GenomeWithHypothesis
from src.exceptions import LLMError
from src.models.genome import GenePool
from tests.conftest import GENE_POOL_SEED_PATH


def _make_tool_use_block(
    genome: dict[str, str],
    hypothesis: str = "Test hypothesis",
    tool_name: str = "create_variant",
) -> SimpleNamespace:
    """Build a mock ContentBlock that looks like a tool_use response."""
    tool_input = {**genome, "hypothesis": hypothesis}
    return SimpleNamespace(
        type="tool_use",
        name=tool_name,
        input=dict(tool_input),  # copy so pop doesn't affect original
    )


def _make_text_block(text: str) -> SimpleNamespace:
    """Build a mock text ContentBlock."""
    return SimpleNamespace(type="text", text=text)


def _make_response(*blocks: SimpleNamespace) -> SimpleNamespace:
    """Build a mock Anthropic messages.create response."""
    return SimpleNamespace(
        stop_reason="end_turn",
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def _valid_genome() -> dict[str, str]:
    """Return a genome dict with values known to be in the seed gene pool."""
    return {
        "headline": "Limited time: 40% off today only",
        "subhead": "Join 12,000+ happy customers",
        "cta_text": "Get started free",
        "cta_color": "green",
        "hero_style": "lifestyle_photo",
        "social_proof": "customer_count",
        "urgency": "time_limited",
        "audience": "retargeting_30d",
    }


def _alt_genome() -> dict[str, str]:
    """Return a different valid genome (one slot changed)."""
    g = _valid_genome()
    g["cta_color"] = "blue"
    return g


@pytest.fixture()
def gene_pool_fixture() -> GenePool:
    return GenePool.from_file(GENE_POOL_SEED_PATH)


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Return an AsyncMock of anthropic.AsyncAnthropic."""
    client = AsyncMock()
    client.messages = AsyncMock()
    client.messages.create = AsyncMock()
    return client


class TestGeneratorAgent:
    """Tests for GeneratorAgent.generate_variants()."""

    async def test_generate_variants_returns_validated_genomes(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """Valid tool-use responses should produce validated GenomeWithHypothesis."""
        genome = _valid_genome()
        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(genome, "Testing green CTA")
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 1
        assert isinstance(results[0], GenomeWithHypothesis)
        assert results[0].genome == genome
        assert results[0].hypothesis == "Testing green CTA"

    async def test_multiple_valid_variants(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """Multiple valid tool-use blocks should produce multiple results."""
        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(_valid_genome(), "Hypothesis A"),
            _make_tool_use_block(_alt_genome(), "Hypothesis B"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 2

    async def test_invalid_genome_is_skipped(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """A genome with an invalid value should be skipped; valid ones kept."""
        invalid_genome = _valid_genome()
        invalid_genome["cta_color"] = "INVALID_COLOR"  # not in gene pool

        valid_genome = _alt_genome()

        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(invalid_genome, "Bad one"),
            _make_tool_use_block(valid_genome, "Good one"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 1
        assert results[0].genome == valid_genome

    async def test_duplicate_genomes_are_filtered(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """Duplicate genomes (same as each other or existing) should be filtered."""
        genome = _valid_genome()

        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(genome, "First"),
            _make_tool_use_block(genome, "Duplicate"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 1  # second was a duplicate

    async def test_duplicate_of_existing_variant_is_filtered(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """A genome matching an existing variant should be skipped."""
        genome = _valid_genome()

        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(genome, "Already exists"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")

        with pytest.raises(LLMError, match="failed to produce"):
            await agent.generate_variants(
                gene_pool=gene_pool_fixture,
                element_rankings=[],
                top_interactions=[],
                current_variants=[genome],  # already exists
                max_new=3,
            )

    async def test_no_valid_variants_raises_llm_error(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """If all LLM outputs are invalid, LLMError should be raised."""
        invalid = _valid_genome()
        invalid["headline"] = "TOTALLY FAKE"

        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(invalid, "All bad"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")

        with pytest.raises(LLMError, match="failed to produce"):
            await agent.generate_variants(
                gene_pool=gene_pool_fixture,
                element_rankings=[],
                top_interactions=[],
                current_variants=[],
                max_new=3,
            )

    async def test_wrong_tool_name_is_skipped(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """If the LLM calls the wrong tool, that block should be ignored."""
        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(_valid_genome(), "wrong tool", tool_name="wrong_tool"),
            _make_tool_use_block(_alt_genome(), "correct tool"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 1
        assert results[0].genome == _alt_genome()

    async def test_max_new_is_respected(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """No more than max_new variants should be returned."""
        g1 = _valid_genome()
        g2 = _alt_genome()
        g3 = _valid_genome()
        g3["hero_style"] = "illustration"

        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(g1, "H1"),
            _make_tool_use_block(g2, "H2"),
            _make_tool_use_block(g3, "H3"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=2,
        )

        assert len(results) == 2

    async def test_text_blocks_are_ignored(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """Text content blocks should be skipped, only tool_use matters."""
        mock_client.messages.create.return_value = _make_response(
            _make_text_block("Here are my suggestions:"),
            _make_tool_use_block(_valid_genome(), "H1"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 1

    async def test_missing_slot_in_genome_is_skipped(
        self, mock_client: AsyncMock, gene_pool_fixture: GenePool
    ) -> None:
        """A genome missing a required slot should fail Pydantic validation."""
        incomplete = _valid_genome()
        del incomplete["audience"]  # remove required slot

        valid = _alt_genome()

        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(incomplete, "Missing slot"),
            _make_tool_use_block(valid, "Valid"),
        )

        agent = GeneratorAgent(client=mock_client, model="claude-sonnet-4-20250514")
        results = await agent.generate_variants(
            gene_pool=gene_pool_fixture,
            element_rankings=[],
            top_interactions=[],
            current_variants=[],
            max_new=3,
        )

        assert len(results) == 1
        assert results[0].genome == valid
