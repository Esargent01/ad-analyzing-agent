"""Phase H: typed approval queue items for the ``/experiments`` API.

Before Phase H the ``approval_queue`` held only "proposed new variant"
rows, which the dashboard surfaced as :class:`ProposedVariant` from
``src/models/reports.py``. Phase H generalised the queue to hold four
kinds of rows (``new_variant``, ``pause_variant``, ``scale_budget``,
``promote_winner``) so the agent can propose pause/scale decisions
instead of executing them autonomously.

This module defines a **discriminated union** that the experiments
endpoint returns: every variant of :class:`PendingApproval` carries a
literal ``kind`` tag so the frontend can render the right card
(``ProposedVariantCard``, ``ProposedPauseCard``, ``ProposedScaleCard``)
without inspecting payload shapes. Pydantic v2 uses the ``kind`` field
as the discriminator and validates each branch against its own model.

Payload shapes mirror what the orchestrator writes into
``action_payload`` in ``src/db/queries.py`` — keep them in sync when
evolving either side.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared evidence block
# ---------------------------------------------------------------------------


class PauseEvidence(BaseModel):
    """Stats that convinced the agent a variant should be paused.

    The reason field distinguishes stats-driven pauses (a variant lost
    a two-proportion z-test against the baseline) from fatigue-driven
    pauses (CTR has declined for 3+ consecutive days). Evidence fields
    beyond ``reason`` are optional because fatigue rows don't have a
    p-value and stats rows don't have a trend slope.
    """

    model_config = ConfigDict(extra="allow")

    reason: Literal["statistically_significant_loser", "audience_fatigue"]
    variant_ctr: float | None = None
    baseline_ctr: float | None = None
    p_value: float | None = None
    z_score: float | None = None
    impressions: int | None = None
    clicks: int | None = None
    consecutive_decline_days: int | None = None
    trend_slope: float | None = None


class ScaleEvidence(BaseModel):
    """Posterior stats that drove a Thompson-sampling budget proposal."""

    model_config = ConfigDict(extra="allow")

    allocation_method: str = "thompson_sampling"
    impressions: int | None = None
    clicks: int | None = None
    posterior_mean: float | None = None
    share_of_allocation: float | None = None


# ---------------------------------------------------------------------------
# Discriminated union branches
# ---------------------------------------------------------------------------


class PendingNewVariant(BaseModel):
    """A proposed new variant awaiting approval.

    The pre-Phase-H ``ProposedVariant`` shape, now just one branch of
    the pending approvals union. ``classification`` and
    ``days_until_expiry`` are populated by ``load_proposed_variants``
    so the dashboard can badge "expiring soon" rows.
    """

    model_config = ConfigDict(strict=False)

    kind: Literal["new_variant"] = "new_variant"
    approval_id: UUID
    variant_id: UUID | None
    variant_code: str
    genome: dict[str, str]
    genome_summary: str
    hypothesis: str | None
    submitted_at: datetime
    classification: str  # "new" or "expiring_soon"
    days_until_expiry: int


class PendingPauseVariant(BaseModel):
    """A pause proposal for a currently-running ad.

    ``deployment_id`` + ``platform_ad_id`` come from the underlying
    deployment row; the dashboard uses ``platform_ad_id`` to link back
    to Meta Ads Manager for a sanity-check "yes, this is the ad I
    think it is" moment before the user confirms. ``genome_snapshot``
    is the copy + media combination that was running at the time the
    proposal was queued — useful context for the approval card.
    """

    model_config = ConfigDict(strict=False)

    kind: Literal["pause_variant"] = "pause_variant"
    approval_id: UUID
    campaign_id: UUID
    deployment_id: UUID
    platform_ad_id: str
    variant_code: str | None = None
    genome_snapshot: dict[str, str] = Field(default_factory=dict)
    reason: Literal["statistically_significant_loser", "audience_fatigue"]
    evidence: PauseEvidence
    submitted_at: datetime


class PendingScaleBudget(BaseModel):
    """A budget-change proposal for a currently-running ad.

    ``current_budget`` and ``proposed_budget`` are both Decimals
    serialised from float in the payload. The UI shows a simple
    "old → new" arrow and the evidence block underneath.
    """

    model_config = ConfigDict(strict=False)

    kind: Literal["scale_budget"] = "scale_budget"
    approval_id: UUID
    campaign_id: UUID
    deployment_id: UUID
    platform_ad_id: str
    variant_code: str | None = None
    genome_snapshot: dict[str, str] = Field(default_factory=dict)
    current_budget: Decimal
    proposed_budget: Decimal
    reason: str = "thompson_sampling"
    evidence: ScaleEvidence
    submitted_at: datetime


class PendingPromoteWinner(BaseModel):
    """Placeholder branch for future "mark winner + pause losers" flows.

    Included so the enum is forward-compatible and the frontend's
    exhaustive-match falls through to an explicit "coming soon" rather
    than a runtime error. No orchestrator code queues rows with this
    kind yet.
    """

    model_config = ConfigDict(strict=False)

    kind: Literal["promote_winner"] = "promote_winner"
    approval_id: UUID
    variant_id: UUID | None
    variant_code: str
    submitted_at: datetime


PendingApproval = Annotated[
    PendingNewVariant | PendingPauseVariant | PendingScaleBudget | PendingPromoteWinner,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Approval digest (nightly email nudge)
# ---------------------------------------------------------------------------


class ApprovalDigestEntry(BaseModel):
    """One row of the daily approval digest email — one per user.

    Used by ``src.main.send_approval_digests`` to build the per-owner
    nudge. The digest only shows counts, not individual proposals, so
    even a user who's fallen behind by 30+ items gets a single readable
    email rather than a 30-row wall.
    """

    model_config = ConfigDict(strict=False)

    user_id: UUID
    email: str
    total_pending: int
    by_action_type: dict[str, int]
