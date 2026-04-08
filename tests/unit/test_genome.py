"""Tests for GenomeSchema and GenePool validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.exceptions import GenomeValidationError
from src.models.genome import GenePool, GenomeSchema
from tests.conftest import GENE_POOL_SEED_PATH


class TestGenomeSchema:
    """Tests for the GenomeSchema Pydantic model."""

    def test_valid_genome_creation(self, sample_genome: GenomeSchema) -> None:
        """A genome with all valid slots should be created without error."""
        assert sample_genome.headline == "Limited time: 40% off today only"
        assert sample_genome.media_asset == "placeholder_lifestyle"

    def test_to_dict_returns_all_slots(self, sample_genome: GenomeSchema) -> None:
        """to_dict() should include all 5 slot keys."""
        d = sample_genome.to_dict()
        expected_keys = {
            "headline",
            "subhead",
            "cta_text",
            "media_asset",
            "audience",
        }
        assert set(d.keys()) == expected_keys

    def test_missing_slot_raises_validation_error(self) -> None:
        """Omitting a required slot must raise a ValidationError."""
        with pytest.raises(ValidationError):
            GenomeSchema(
                headline="Limited time: 40% off today only",
                subhead="Join 12,000+ happy customers",
                # cta_text missing
                media_asset="placeholder_lifestyle",
                audience="retargeting_30d",
            )

    def test_extra_slot_raises_validation_error(self) -> None:
        """Extra fields should be rejected by the strict model."""
        with pytest.raises(ValidationError):
            GenomeSchema(
                headline="Limited time: 40% off today only",
                subhead="Join 12,000+ happy customers",
                cta_text="Get started free",
                media_asset="placeholder_lifestyle",
                audience="retargeting_30d",
                bonus_slot="unexpected",
            )

    def test_non_string_value_raises_validation_error(self) -> None:
        """Strict mode rejects non-string slot values (e.g. int)."""
        with pytest.raises(ValidationError):
            GenomeSchema(
                headline=42,  # type: ignore[arg-type]
                subhead="Join 12,000+ happy customers",
                cta_text="Get started free",
                media_asset="placeholder_lifestyle",
                audience="retargeting_30d",
            )

    def test_genome_is_frozen(self, sample_genome: GenomeSchema) -> None:
        """GenomeSchema is frozen -- attribute assignment must fail."""
        with pytest.raises(ValidationError):
            sample_genome.headline = "changed"  # type: ignore[misc]

    def test_validate_against_pool_valid(
        self, sample_genome: GenomeSchema, gene_pool: GenePool
    ) -> None:
        """A genome with all values from the pool passes validation."""
        # Should not raise
        sample_genome.validate_against_pool(gene_pool)

    def test_validate_against_pool_invalid_value(self, gene_pool: GenePool) -> None:
        """A genome with a value NOT in the pool must raise GenomeValidationError."""
        genome = GenomeSchema(
            headline="NOT A REAL HEADLINE",
            subhead="Join 12,000+ happy customers",
            cta_text="Get started free",
            media_asset="placeholder_lifestyle",
            audience="retargeting_30d",
        )
        with pytest.raises(GenomeValidationError, match="headline"):
            genome.validate_against_pool(gene_pool)


class TestGenePool:
    """Tests for the GenePool model and file loading."""

    def test_from_file_loads_all_slots(self) -> None:
        """GenePool.from_file() should load all 5 slots from the seed file."""
        pool = GenePool.from_file(GENE_POOL_SEED_PATH)
        expected_slots = {
            "headline",
            "subhead",
            "cta_text",
            "media_asset",
            "audience",
        }
        assert set(pool.all_slot_names()) == expected_slots

    def test_allowed_values_for_returns_strings(self) -> None:
        """allowed_values_for() should return a set of string values."""
        pool = GenePool.from_file(GENE_POOL_SEED_PATH)
        ctas = pool.allowed_values_for("cta_text")
        assert isinstance(ctas, set)
        assert "Get started free" in ctas
        assert "Learn more" in ctas
        assert "nonexistent" not in ctas

    def test_allowed_values_for_headline(self) -> None:
        """Headline slot should have multiple entries from the seed file."""
        pool = GenePool.from_file(GENE_POOL_SEED_PATH)
        headlines = pool.allowed_values_for("headline")
        assert len(headlines) >= 4
        assert "Limited time: 40% off today only" in headlines

    def test_from_file_nonexistent_path_raises(self) -> None:
        """Loading from a non-existent path should raise an error."""
        with pytest.raises(FileNotFoundError):
            GenePool.from_file("/tmp/nonexistent_gene_pool_zzz.json")

    def test_empty_slot_raises_validation_error(self) -> None:
        """A gene pool with an empty slot list must raise ValueError."""
        data = {
            "headline": [],  # empty
            "subhead": [{"value": "x", "description": "d"}],
            "cta_text": [{"value": "x", "description": "d"}],
            "media_asset": [{"value": "x", "description": "d"}],
            "audience": [{"value": "x", "description": "d"}],
        }
        with pytest.raises(ValueError, match="headline"):
            GenePool.model_validate(data)
