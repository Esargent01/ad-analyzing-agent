"""Variant Pydantic models and status enum."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VariantStatus(str, enum.Enum):
    """Maps to the variant_status enum in PostgreSQL."""

    DRAFT = "draft"
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    WINNER = "winner"
    RETIRED = "retired"


class VariantCreate(BaseModel):
    """Payload for creating a new variant."""

    model_config = ConfigDict(strict=True)

    campaign_id: UUID
    genome: dict[str, str]
    generation: int
    parent_ids: list[UUID] = []
    hypothesis: str | None = None


class VariantResponse(BaseModel):
    """Read-only representation of a variant returned from the database."""

    model_config = ConfigDict(strict=True, from_attributes=True)

    id: UUID
    campaign_id: UUID
    variant_code: str
    genome: dict[str, str]
    status: VariantStatus
    generation: int
    parent_ids: list[UUID]
    hypothesis: str | None
    created_at: datetime
    deployed_at: datetime | None
    paused_at: datetime | None
    retired_at: datetime | None
