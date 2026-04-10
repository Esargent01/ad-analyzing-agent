"""Pydantic models for the Phase D self-serve import flow.

The import flow lets a signed-in user pick campaigns from their own
Meta ad account and bring them into the system. These models are the
contract between the backend endpoints and the frontend picker page.

Keep them free of ORM references — they're serialised straight to
JSON and also re-exported through ``openapi-typescript`` for the
frontend.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ImportableCampaign(BaseModel):
    """A single row in the Meta campaign picker.

    Mirrors the dict returned by ``MetaAdapter.list_campaigns``,
    plus a flag that tells the UI whether this campaign has already
    been imported for the current user (greyed out + can't
    re-import).
    """

    model_config = ConfigDict(strict=True)

    meta_campaign_id: str
    name: str
    status: str
    daily_budget: Optional[float] = None
    created_time: Optional[datetime] = None
    objective: Optional[str] = None
    already_imported: bool = False


class ImportableCampaignsResponse(BaseModel):
    """Wrapper for the picker page payload — list + quota info."""

    model_config = ConfigDict(strict=True)

    importable: list[ImportableCampaign]
    quota_used: int
    quota_max: int


class CampaignImportOverrides(BaseModel):
    """Optional per-campaign settings the user can tweak at import time."""

    model_config = ConfigDict(strict=True)

    daily_budget: Optional[Decimal] = Field(default=None, ge=0)
    max_concurrent_variants: Optional[int] = Field(default=None, ge=1, le=50)
    confidence_threshold: Optional[Decimal] = Field(
        default=None, ge=Decimal("0.5"), le=Decimal("0.999")
    )


class CampaignImportRequest(BaseModel):
    """POST body for ``/api/me/meta/campaigns/import``."""

    model_config = ConfigDict(strict=True)

    meta_campaign_ids: list[str] = Field(min_length=1)
    overrides: CampaignImportOverrides = Field(
        default_factory=CampaignImportOverrides
    )


class ImportedCampaignSummary(BaseModel):
    """One row in the import result — a newly-created Campaign."""

    model_config = ConfigDict(strict=True)

    id: UUID
    name: str
    platform_campaign_id: str
    daily_budget: Decimal
    seeded_gene_pool_entries: int
    registered_deployments: int


class CampaignImportFailure(BaseModel):
    """One row in the import result — a campaign that failed to import."""

    model_config = ConfigDict(strict=True)

    meta_campaign_id: str
    error: str


class CampaignImportResult(BaseModel):
    """Aggregate result of a bulk import attempt.

    The endpoint returns 200 with this body even on partial failure
    — individual errors are surfaced per-row so the UI can show
    successes and failures side-by-side.
    """

    model_config = ConfigDict(strict=True)

    imported: list[ImportedCampaignSummary]
    failed: list[CampaignImportFailure]
    quota_used_after: int
    quota_max: int
