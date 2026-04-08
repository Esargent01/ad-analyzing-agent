"""Genome and gene pool Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from src.exceptions import GenomeValidationError


class GenomeSchema(BaseModel):
    """A creative genome — one value per slot, all drawn from the gene pool.

    Slots map directly to ad platform fields:
    - headline: Ad headline text
    - subhead: Primary text / body copy
    - cta_text: Call-to-action button text
    - media_asset: Reference to a real image or video asset
    - audience: Targeting group (mapped to platform audience IDs)
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    headline: str
    subhead: str
    cta_text: str
    media_asset: str
    audience: str

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
    Each slot maps directly to a controllable ad element.
    """

    model_config = ConfigDict(strict=True)

    headline: list[GenePoolEntry]
    subhead: list[GenePoolEntry]
    cta_text: list[GenePoolEntry]
    media_asset: list[GenePoolEntry] = []  # populated from media_assets table
    audience: list[GenePoolEntry]

    # media_asset can start empty — populated when media is synced from platform
    _OPTIONAL_SLOTS: set[str] = {"media_asset"}

    @model_validator(mode="after")
    def _ensure_required_slots_non_empty(self) -> GenePool:
        for slot_name in self.__class__.model_fields:
            if slot_name.startswith("_"):
                continue
            entries: list[GenePoolEntry] = getattr(self, slot_name)
            if len(entries) == 0 and slot_name not in self._OPTIONAL_SLOTS:
                raise ValueError(f"Gene pool slot '{slot_name}' must have at least one entry")
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
