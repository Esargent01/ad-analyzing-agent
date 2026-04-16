"""Draft a single daily marketing tweet from a DailyReport.

The Kleiber brand X account tweets once a day about the showcase
campaign's performance. This module turns the structured
``DailyReport`` Pydantic model into a single tweet body, via Claude
tool use so the output is schema-constrained. Mirrors the Anthropic
integration pattern from ``src.agents.generator`` — the Anthropic
SDK directly, Pydantic validation on the tool-use result, usage
logging through the existing ``log_llm_call`` plumbing.

The writer is allowed to *skip* a day by returning the sentinel
``"__SKIP__"`` when the day's data is too thin to say anything
interesting (no purchases, no best variant, no actions). The caller
treats this as a silent no-op rather than posting a low-signal tweet.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.exceptions import LLMError
from src.services.usage import AgentContext, log_llm_call

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.models.reports import DailyReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice guide. Lives here as a module constant per CLAUDE.md conventions.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You write a single tweet per day for the Kleiber brand X account.
Kleiber is an autonomous ad-testing agent — it monitors Meta ads,
pauses losers, scales winners, and generates new variant ideas.
Today's report is from Kleiber's own showcase Meta campaign (i.e.
Kleiber running Kleiber's ads). You are writing in Kleiber's voice
to Kleiber's audience of performance marketers and founders.

VOICE:
- Confident, data-forward, dry. Not salesy. Not hype.
- Lead with the number, not the caveat.
- One concrete proof point per tweet — the best variant's genome \
summary, a CPA delta, or a specific action taken.
- No emojis. No hashtags. No "🚀" or "🔥". No "Exciting news!".
- Plain lowercase or sentence case. No ALL CAPS.
- OK to say what the agent did ("paused 2 losers", "scaled the \
winner 4x"). Never pretend a human did it.

HARD LIMITS:
- Max 280 characters INCLUDING spaces and punctuation.
- Min 20 characters.
- No links.

WHEN TO SKIP:
If the report has zero purchases AND no best variant AND no actions \
taken (i.e. nothing interesting happened), call the publish_tweet \
tool with text="__SKIP__". The cron will log and move on.

You MUST call the publish_tweet tool exactly once. Do not output \
raw text.
"""


# ---------------------------------------------------------------------------
# Pydantic output model — also the validation gate for the tool input.
# ---------------------------------------------------------------------------


class TweetDraft(BaseModel):
    """A validated tweet body (or the SKIP sentinel)."""

    model_config = ConfigDict(strict=True)

    text: str = Field(..., min_length=8, max_length=280)


SKIP_SENTINEL = "__SKIP__"


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------


_PUBLISH_TWEET_TOOL = {
    "name": "publish_tweet",
    "description": (
        "Publish the final tweet for today. Call this exactly once. "
        f"Use text={SKIP_SENTINEL!r} to skip the day when there is no "
        "meaningful signal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The tweet body. Must be 20–280 characters for a real tweet, "
                    f"or the exact string {SKIP_SENTINEL!r} to skip this day."
                ),
                "minLength": 8,
                "maxLength": 280,
            },
        },
        "required": ["text"],
    },
}


# ---------------------------------------------------------------------------
# Report → prompt serializer
# ---------------------------------------------------------------------------


def _serialize_report_for_prompt(report: DailyReport) -> str:
    """Flatten a DailyReport into a compact prompt-friendly blob.

    We deliberately don't dump every field — the model doesn't need
    to see every funnel stage. We feed it the top-line aggregates,
    the best variant's key metrics, a count of actions taken, and
    whatever day-over-day deltas are available.
    """
    delta_cpa: str | None = None
    if (
        report.avg_cost_per_purchase is not None
        and report.prev_avg_cpa is not None
        and report.prev_avg_cpa > 0
    ):
        delta = (report.avg_cost_per_purchase - report.prev_avg_cpa) / report.prev_avg_cpa
        delta_cpa = f"{delta:+.1%}"

    best: dict[str, object] | None = None
    if report.best_variant is not None:
        bv = report.best_variant
        best = {
            "variant_code": bv.variant_code,
            "genome_summary": bv.genome_summary,
            "hypothesis": bv.hypothesis,
            "cost_per_purchase": bv.cost_per_purchase,
            "roas": bv.roas,
            "purchases": bv.purchases,
            "hook_rate_pct": bv.hook_rate_pct,
            "ctr_pct": bv.ctr_pct,
        }

    actions_summary = [
        {"action_type": a.action_type, "variant_code": a.variant_code}
        for a in report.actions
    ]

    payload = {
        "date": report.report_date.isoformat(),
        "day_number": report.day_number,
        "cycle_number": report.cycle_number,
        "total_spend": float(report.total_spend),
        "total_purchases": report.total_purchases,
        "avg_cpa": report.avg_cost_per_purchase,
        "avg_roas": report.avg_roas,
        "cpa_delta_vs_prev_day": delta_cpa,
        "best_variant": best,
        "num_actions_taken": len(report.actions),
        "actions": actions_summary,
        "num_winners": len(report.winners),
        "num_fatigue_alerts": len(report.fatigue_alerts),
    }
    return json.dumps(payload, default=str, indent=2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def draft_daily_tweet(
    report: DailyReport,
    client: anthropic.AsyncAnthropic,
    model: str,
    usage_session: AsyncSession | None = None,
    usage_context: AgentContext | None = None,
) -> TweetDraft:
    """Use Claude tool use to produce a single tweet draft.

    Args:
        report: The already-built ``DailyReport`` for the showcase
            campaign.
        client: An initialized ``anthropic.AsyncAnthropic``.
        model: The Anthropic model identifier (usually
            ``settings.anthropic_model``).
        usage_session: Optional DB session for ``usage_log`` writes.
        usage_context: Optional attribution context.

    Returns:
        A validated ``TweetDraft``. ``draft.text`` is either a 8–280
        char tweet body or the literal ``"__SKIP__"`` sentinel.

    Raises:
        LLMError: If the API call fails or the model fails to produce
            a tool-use block after one retry.
    """
    user_message = (
        "Here is today's showcase-campaign report. Write one tweet.\n\n"
        f"```json\n{_serialize_report_for_prompt(report)}\n```"
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            tools=[_PUBLISH_TWEET_TOOL],
            tool_choice={"type": "tool", "name": "publish_tweet"},
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        logger.error(
            "Anthropic API error while drafting tweet: %s (status=%s)",
            exc,
            getattr(exc, "status_code", None),
        )
        raise LLMError(f"Tweet drafter failed: {exc}") from exc

    # Best-effort usage log. Never failable.
    if usage_session is not None and usage_context is not None:
        try:
            await log_llm_call(
                usage_session,
                usage_context,
                model=model,
                input_tokens=int(response.usage.input_tokens),
                output_tokens=int(response.usage.output_tokens),
                metadata={"stop_reason": response.stop_reason, "agent": "tweet_writer"},
            )
        except Exception as log_exc:  # noqa: BLE001
            logger.warning("Failed to log tweet drafter usage: %s", log_exc)

    for block in response.content:
        if block.type == "tool_use" and block.name == "publish_tweet":
            try:
                return TweetDraft.model_validate(block.input)
            except ValidationError as exc:
                logger.warning(
                    "Tweet writer returned invalid draft: %s — input was %s",
                    exc,
                    block.input,
                )
                raise LLMError(f"Tweet draft failed Pydantic validation: {exc}") from exc

    raise LLMError(
        "Tweet writer did not produce a publish_tweet tool_use block "
        f"(stop_reason={response.stop_reason})"
    )
