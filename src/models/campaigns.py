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
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.oauth import MetaAdAccountInfo, MetaPageInfo


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
    daily_budget: float | None = None
    created_time: datetime | None = None
    objective: str | None = None
    already_imported: bool = False


class ImportableCampaignsResponse(BaseModel):
    """Wrapper for the picker page payload — list + quota info.

    Phase G extended this with the user's full set of ad accounts and
    Pages plus the auto-picked defaults, so the frontend picker page
    can render account/Page dropdowns without a second roundtrip.
    """

    model_config = ConfigDict(strict=True)

    importable: list[ImportableCampaign]
    quota_used: int
    quota_max: int
    # Phase G — available assets for the account/Page dropdowns. Empty
    # lists are valid (brand-new Facebook account with nothing set up).
    available_ad_accounts: list[MetaAdAccountInfo] = Field(default_factory=list)
    available_pages: list[MetaPageInfo] = Field(default_factory=list)
    default_ad_account_id: str | None = None
    default_page_id: str | None = None
    # The account the ``importable`` list was actually fetched against.
    # When this is NULL the caller passed ``ad_account_id=None`` *and*
    # the user has no default, which means the UI should prompt for
    # an account before showing any campaigns.
    selected_ad_account_id: str | None = None


class CampaignImportOverrides(BaseModel):
    """Optional per-campaign settings the user can tweak at import time."""

    model_config = ConfigDict(strict=True)

    daily_budget: Decimal | None = Field(default=None, ge=0)
    max_concurrent_variants: int | None = Field(default=None, ge=1, le=50)
    confidence_threshold: Decimal | None = Field(
        default=None, ge=Decimal("0.5"), le=Decimal("0.999")
    )


class CampaignImportRequest(BaseModel):
    """POST body for ``/api/me/meta/campaigns/import``.

    Phase G made ``ad_account_id`` and ``page_id`` required on every
    import. The backend validates both are in the user's
    ``available_ad_accounts`` / ``available_pages`` allowlist so a
    malicious POST can't target another user's ad account even if the
    attacker somehow knows its id.

    ``landing_page_url`` is optional — some product pages are set up
    on the ad side (with a placeholder URL here) and some are carried
    through from the Meta ad creative. Users can edit it later.
    """

    model_config = ConfigDict(strict=True)

    meta_campaign_ids: list[str] = Field(min_length=1)
    overrides: CampaignImportOverrides = Field(default_factory=CampaignImportOverrides)
    ad_account_id: str = Field(min_length=1)
    page_id: str = Field(min_length=1)
    landing_page_url: str | None = None


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
