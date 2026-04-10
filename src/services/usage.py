"""Per-user cost tracking for LLM and Meta API calls (Phase E).

Every externally-billable operation the system performs writes one
row to the ``usage_log`` hypertable through the helpers in this
module. That turns "how much did this campaign cost its owner this
month?" from a spreadsheet question into a SQL query.

Two things live here:

1. ``PRICING`` — a hand-maintained table of Anthropic Claude model
   prices in USD per 1M tokens. This is the single source of truth
   for cost math. We intentionally commit it to source instead of
   fetching from the Anthropic SDK, because (a) the SDK doesn't
   expose prices and (b) auditable cost math is a compliance
   requirement for any downstream billing feature.
2. ``AgentContext`` + the two ``log_*`` helpers — a small
   dataclass carrying the "who's paying for this call" metadata
   and functions that turn an Anthropic ``Usage`` object or a
   Meta method name into a ``UsageLog`` row.

Agents (``src.agents.*``) and the Meta adapter opt in by accepting
an optional ``AgentContext`` in their constructors. When set, they
call back into this module after each external operation. When
``None`` (unit-test path, legacy code) they skip logging entirely,
which keeps the Phase E rollout hermetic for the existing test
suite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.tables import UsageLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing table — Anthropic Claude models, USD per 1,000,000 tokens.
# ---------------------------------------------------------------------------
#
# Sources:
# - https://www.anthropic.com/pricing (as of 2026-04)
# - Sonnet 4.5: $3.00 input / $15.00 output per MTok
# - Haiku 4.5:  $1.00 input / $5.00 output per MTok
# - Opus 4.1:   $15.00 input / $75.00 output per MTok
#
# Keep this dict narrow: one entry per model ID we actually send
# traffic to. Unknown model IDs fall back to the Sonnet tier so
# cost estimates are conservative rather than zero.

PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # (input_per_mtok, output_per_mtok)
    "claude-sonnet-4-20250514": (Decimal("3.00"), Decimal("15.00")),
    "claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-opus-4-1": (Decimal("15.00"), Decimal("75.00")),
    "claude-3-5-sonnet-20241022": (Decimal("3.00"), Decimal("15.00")),
    "claude-3-5-haiku-20241022": (Decimal("0.80"), Decimal("4.00")),
}

# Fallback pricing for unknown models — Sonnet tier. Better to
# over-estimate than silently log $0.00.
_DEFAULT_PRICING: tuple[Decimal, Decimal] = (Decimal("3.00"), Decimal("15.00"))

# One million tokens — used to normalise the per-MTok pricing into
# per-token math without losing precision.
_MTOK: Decimal = Decimal("1000000")


# Service identifiers used in the ``service`` column.
SERVICE_LLM: str = "llm"
SERVICE_META: str = "meta_api"
SERVICE_EMAIL: str = "email"


# ---------------------------------------------------------------------------
# Cost calculation helpers
# ---------------------------------------------------------------------------


def calculate_llm_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Return the USD cost of an LLM call.

    Pure computation — no I/O. Exposed so tests and other callers
    can reason about prices without going through the DB logger.

    Unknown model IDs fall back to ``_DEFAULT_PRICING`` so cost is
    never silently zero. A warning is logged on fallback so the
    pricing table gets updated eventually.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError(
            f"Token counts must be non-negative, got "
            f"input={input_tokens}, output={output_tokens}"
        )
    if model in PRICING:
        input_rate, output_rate = PRICING[model]
    else:
        logger.warning(
            "Unknown model %r in cost calculation — falling back to default pricing",
            model,
        )
        input_rate, output_rate = _DEFAULT_PRICING

    input_cost = (Decimal(input_tokens) / _MTOK) * input_rate
    output_cost = (Decimal(output_tokens) / _MTOK) * output_rate
    # Round to 6 decimal places so we never log sub-micro values
    # that would confuse the UI and clutter aggregations.
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


# ---------------------------------------------------------------------------
# Agent context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentContext:
    """Carries the "who/what/why" for a billable external call.

    Threaded through agent + adapter constructors so the logging
    helpers can attribute each row to a user, campaign, and cycle
    without every call site re-computing them.

    ``user_id`` and ``campaign_id`` are optional because some
    maintenance calls (seed scripts, CLI one-offs) legitimately
    don't have an owning user or campaign. In those cases the
    row lands with NULLs and still counts toward the service-
    level aggregate.
    """

    user_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    cycle_id: Optional[UUID] = None
    agent: Optional[str] = None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


async def log_llm_call(
    session: AsyncSession,
    ctx: AgentContext,
    model: str,
    input_tokens: int,
    output_tokens: int,
    metadata: Optional[dict[str, object]] = None,
) -> UsageLog:
    """Insert a ``usage_log`` row for a single LLM API call.

    Called from agents right after an ``anthropic.messages.create``
    returns. The caller passes the ``response.usage`` fields
    directly. Cost is computed via ``calculate_llm_cost``.

    The caller owns the session — we do not commit. Flushing is
    the caller's responsibility (usually at orchestrator cycle
    boundaries).
    """
    cost = calculate_llm_cost(model, input_tokens, output_tokens)
    row = UsageLog(
        recorded_at=datetime.now(timezone.utc),
        user_id=ctx.user_id,
        campaign_id=ctx.campaign_id,
        cycle_id=ctx.cycle_id,
        service=SERVICE_LLM,
        agent=ctx.agent,
        model=model,
        input_units=input_tokens,
        output_units=output_tokens,
        cost_usd=cost,
        metadata_json=metadata,
    )
    session.add(row)
    logger.debug(
        "Logged LLM usage: agent=%s model=%s in=%d out=%d cost=$%s",
        ctx.agent,
        model,
        input_tokens,
        output_tokens,
        cost,
    )
    return row


async def log_meta_call(
    session: AsyncSession,
    ctx: AgentContext,
    method: str,
    cost_usd: Decimal = Decimal("0"),
    metadata: Optional[dict[str, object]] = None,
) -> UsageLog:
    """Insert a ``usage_log`` row for a single Meta API method call.

    Meta's Marketing API is free for typical usage but comes with
    per-app and per-user rate limits. We still log every call so
    (a) Phase G can build rate-limit dashboards without a backfill
    and (b) if Meta ever starts charging, the cost column is
    already the right shape.

    ``cost_usd`` defaults to 0 and is exposed in case a caller
    wants to attribute a known unit cost.
    """
    row = UsageLog(
        recorded_at=datetime.now(timezone.utc),
        user_id=ctx.user_id,
        campaign_id=ctx.campaign_id,
        cycle_id=ctx.cycle_id,
        service=SERVICE_META,
        agent=ctx.agent,
        model=None,
        input_units=0,
        output_units=0,
        cost_usd=cost_usd,
        metadata_json={"method": method, **(metadata or {})},
    )
    session.add(row)
    logger.debug(
        "Logged Meta API usage: method=%s campaign=%s", method, ctx.campaign_id
    )
    return row
