"""Slack Block Kit reporter for cycle and weekly summaries."""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from src.models.reports import CycleAction, CycleReport, VariantSummary, WeeklyReport

logger = logging.getLogger(__name__)


def _fmt_decimal(value: Decimal | None, suffix: str = "", prefix: str = "") -> str:
    """Format a Decimal for display, returning 'N/A' when None."""
    if value is None:
        return "N/A"
    return f"{prefix}{value:.4f}{suffix}"


def _fmt_money(value: Decimal | None) -> str:
    """Format a Decimal as currency."""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


class SlackReporter:
    """Sends rich Block Kit messages to a Slack incoming webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_cycle_report(self, report: CycleReport) -> bool:
        """Post a cycle report to Slack. Returns True on success."""
        blocks = self._build_cycle_blocks(report)
        return await self._post(blocks)

    async def send_weekly_report(self, report: WeeklyReport) -> bool:
        """Post a weekly report to Slack. Returns True on success."""
        blocks = self._build_weekly_blocks(report)
        return await self._post(blocks)

    # ------------------------------------------------------------------
    # Block builders
    # ------------------------------------------------------------------

    def _build_cycle_blocks(self, report: CycleReport) -> list[dict[str, object]]:
        """Build Slack Block Kit blocks for a cycle report."""
        blocks: list[dict[str, object]] = []

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Cycle #{report.cycle_number} Complete",
                    "emoji": True,
                },
            }
        )

        # Campaign & timing context
        started = report.started_at.strftime("%Y-%m-%d %H:%M UTC")
        completed = (
            report.completed_at.strftime("%Y-%m-%d %H:%M UTC")
            if report.completed_at
            else "in progress"
        )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*Campaign:* `{report.campaign_id}` | "
                            f"*Phase:* {report.phase} | "
                            f"*Started:* {started} | *Completed:* {completed}"
                        ),
                    }
                ],
            }
        )

        blocks.append({"type": "divider"})

        # Metrics summary
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Metrics Summary*\n"
                        f"- Active variants: *{report.variants_active}*\n"
                        f"- Launched: *{report.variants_launched}* | "
                        f"Paused: *{report.variants_paused}* | "
                        f"Promoted: *{report.variants_promoted}*\n"
                        f"- Total spend: *{_fmt_money(report.total_spend)}*\n"
                        f"- Avg CTR: *{_fmt_decimal(report.avg_ctr)}* | "
                        f"Avg CPA: *{_fmt_money(report.avg_cpa)}*"
                    ),
                },
            }
        )

        blocks.append({"type": "divider"})

        # Top performers (up to 5)
        if report.variant_summaries:
            sorted_variants = sorted(
                report.variant_summaries,
                key=lambda v: v.ctr,
                reverse=True,
            )
            top = sorted_variants[:5]
            lines = ["*Top Performers*"]
            for v in top:
                lines.append(
                    f"  `{v.variant_code}` — CTR {_fmt_decimal(v.ctr)} | "
                    f"Spend {_fmt_money(v.spend)} | "
                    f"Status: {v.status}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)},
                }
            )

            blocks.append({"type": "divider"})

        # Actions taken
        if report.actions_taken:
            blocks.append(self._build_actions_section(report.actions_taken))
            blocks.append({"type": "divider"})

        # AI summary
        if report.summary_text:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Summary*\n{report.summary_text}",
                    },
                }
            )

        # Error log (if any)
        if report.error_log:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (f":warning: *Errors*\n```{report.error_log[:2900]}```"),
                    },
                }
            )

        return blocks

    def _build_weekly_blocks(self, report: WeeklyReport) -> list[dict[str, object]]:
        """Build Slack Block Kit blocks for a weekly report."""
        blocks: list[dict[str, object]] = []

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Weekly Report: {report.campaign_name}",
                    "emoji": True,
                },
            }
        )

        # Date range context
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*{report.week_start.isoformat()}* to "
                            f"*{report.week_end.isoformat()}* | "
                            f"Cycles run: *{report.cycles_run}*"
                        ),
                    }
                ],
            }
        )

        blocks.append({"type": "divider"})

        # Key metrics
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Key Metrics*\n"
                        f"- Spend: *{_fmt_money(report.total_spend)}*\n"
                        f"- Impressions: *{report.total_impressions:,}*\n"
                        f"- Clicks: *{report.total_clicks:,}*\n"
                        f"- Conversions: *{report.total_conversions:,}*\n"
                        f"- Avg CTR: *{_fmt_decimal(report.avg_ctr)}*\n"
                        f"- Avg CPA: *{_fmt_money(report.avg_cpa)}*"
                    ),
                },
            }
        )

        blocks.append({"type": "divider"})

        # Variant activity
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Variant Activity*\n"
                        f"- Launched: *{report.variants_launched}*\n"
                        f"- Retired: *{report.variants_retired}*"
                    ),
                },
            }
        )

        # Best / worst variant
        if report.best_variant:
            blocks.append(self._build_variant_highlight("Best Variant", report.best_variant))
        if report.worst_variant:
            blocks.append(self._build_variant_highlight("Worst Variant", report.worst_variant))

        blocks.append({"type": "divider"})

        # Top elements (up to 5)
        if report.top_elements:
            lines = ["*Top Elements*"]
            for el in report.top_elements[:5]:
                lines.append(
                    f"  `{el.slot_name}={el.slot_value}` — "
                    f"Avg CTR {_fmt_decimal(el.avg_ctr)} | "
                    f"{el.variants_tested} variants | "
                    f"Confidence {_fmt_decimal(el.confidence)}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)},
                }
            )

        # Top interactions (up to 3)
        if report.top_interactions:
            lines = ["*Top Interactions*"]
            for ix in report.top_interactions[:3]:
                lines.append(
                    f"  `{ix.slot_a_name}={ix.slot_a_value}` + "
                    f"`{ix.slot_b_name}={ix.slot_b_value}` — "
                    f"Lift {_fmt_decimal(ix.interaction_lift, suffix='x')}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)},
                }
            )

        blocks.append({"type": "divider"})

        # Summary
        if report.summary_text:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Summary*\n{report.summary_text}",
                    },
                }
            )

        return blocks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_actions_section(self, actions: list[CycleAction]) -> dict[str, object]:
        """Build a section block listing actions taken."""
        action_icons: dict[str, str] = {
            "launch": ":rocket:",
            "pause": ":double_vertical_bar:",
            "increase_budget": ":chart_with_upwards_trend:",
            "decrease_budget": ":chart_with_downwards_trend:",
            "retire": ":file_folder:",
            "promote_winner": ":trophy:",
        }

        lines = ["*Actions Taken*"]
        for act in actions[:10]:
            icon = action_icons.get(act.action, ":gear:")
            variant_label = f"`{act.variant_code}`" if act.variant_code else "system"
            lines.append(f"  {icon} *{act.action}* {variant_label}")
        if len(actions) > 10:
            lines.append(f"  _...and {len(actions) - 10} more_")
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        }

    def _build_variant_highlight(self, label: str, variant: VariantSummary) -> dict[str, object]:
        """Build a section block for a single variant highlight."""
        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{label}: `{variant.variant_code}`*\n"
                    f"  CTR: {_fmt_decimal(variant.ctr)} | "
                    f"CPA: {_fmt_money(variant.cpa)} | "
                    f"Impressions: {variant.impressions:,} | "
                    f"Spend: {_fmt_money(variant.spend)}"
                ),
            },
        }

    async def _post(self, blocks: list[dict[str, object]]) -> bool:
        """Send a Block Kit payload to the Slack webhook."""
        payload: dict[str, object] = {"blocks": blocks}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self._webhook_url, json=payload)
                if response.status_code == 200 and response.text == "ok":
                    logger.info("Slack message sent successfully.")
                    return True

                logger.error(
                    "Slack webhook returned unexpected response: status=%d body=%s",
                    response.status_code,
                    response.text[:500],
                )
                return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Slack webhook returned HTTP %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("Slack webhook request failed: %s", exc)
            return False
