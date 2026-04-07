"""Genome and gene pool Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from src.exceptions import GenomeValidationError


class GenomeSchema(BaseModel):
    """A creative genome — one value per slot, all drawn from the gene pool.

    The ``media_asset`` slot replaces the older ``hero_style`` slot.
    Both are accepted for backward compatibility with existing genomes,
    but ``media_asset`` is preferred for new variants.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    headline: str
    subhead: str
    cta_text: str
    cta_color: str
    media_asset: str = ""  # new: references a real media asset name
    hero_style: str = ""   # deprecated: kept for backward compat
    social_proof: str
    urgency: str
    audience: str

    @model_validator(mode="after")
    def _require_media_or_hero(self) -> GenomeSchema:
        """Ensure at least one of media_asset or hero_style is set."""
        if not self.media_asset and not self.hero_style:
            raise ValueError(
                "At least one of 'media_asset' or 'hero_style' must be provided"
            )
        return self

    def to_dict(self) -> dict[str, str]:
        """Serialize the genome to a plain dict suitable for JSONB storage."""
        return self.model_dump()

    def validate_against_pool(self, gene_pool: GenePool) -> None:
        """Raise GenomeValidationError if any slot value is not in the pool."""
        genome_dict = self.to_dict()
        for slot_name, slot_value in genome_dict.items():
            allowed = gene_pool.allowed_values_for(slot_name)
            if slot_value not in allowed:
                raise GenomeValidationError(
                    f"Slot '{slot_name}' value '{slot_value}' is not in the gene pool. "
                    f"Allowed: {sorted(allowed)}"
                )


class GenePoolEntry(BaseModel):
    """A single entry in the seed file for one slot value."""

    model_config = ConfigDict(strict=True)

    value: str
    description: str


class GenePool(BaseModel):
    """The full gene pool loaded from gene_pool_seed.json.

    Keys are slot names, values are lists of approved entries.
    ``media_asset`` and ``hero_style`` are both optional — campaigns
    can use either or both depending on whether real media is synced.
    """

    model_config = ConfigDict(strict=True)

    headline: list[GenePoolEntry]
    subhead: list[GenePoolEntry]
    cta_text: list[GenePoolEntry]
    cta_color: list[GenePoolEntry]
    media_asset: list[GenePoolEntry] = []  # populated from media_assets table
    hero_style: list[GenePoolEntry] = []   # legacy slot
    social_proof: list[GenePoolEntry]
    urgency: list[GenePoolEntry]
    audience: list[GenePoolEntry]

    # Slots that are allowed to be empty (optional visual slots)
    _OPTIONAL_SLOTS: set[str] = {"media_asset", "hero_style"}

    @model_validator(mode="after")
    def _ensure_required_slots_non_empty(self) -> GenePool:
        for slot_name in self.__class__.model_fields:
            if slot_name.startswith("_"):
                continue
            entries: list[GenePoolEntry] = getattr(self, slot_name)
            if len(entries) == 0 and slot_name not in self._OPTIONAL_SLOTS:
                raise ValueError(f"Gene pool slot '{slot_name}' must have at least one entry")
        # At least one visual slot must have entries
        if not self.media_asset and not self.hero_style:
            raise ValueError("At least one of 'media_asset' or 'hero_style' must have entries")
        return self

    def allowed_values_for(self, slot_name: str) -> set[str]:
        """Return the set of allowed values for a given slot."""
        entries: list[GenePoolEntry] = getattr(self, slot_name)
        return {entry.value for entry in entries}

    def all_slot_names(self) -> list[str]:
        """Return all slot names in the gene pool."""
        return list(self.__class__.model_fields.keys())

    @classmethod
    def from_file(cls, path: str) -> GenePool:
        """Load a GenePool from a JSON seed file."""
        import json
        from pathlib import Path

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
