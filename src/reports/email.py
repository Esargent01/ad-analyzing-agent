"""Email reporter: renders HTML via Jinja2, sends via SendGrid API."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import jinja2

from src.models.reports import DailyReport, WeeklyReport

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def _format_currency(value: object) -> str:
    v = float(value) if value is not None else 0.0
    if v >= 1000:
        return f"${v:,.0f}"
    return f"${v:.2f}"


def _format_intcomma(value: object) -> str:
    v = int(value) if value is not None else 0
    return f"{v:,}"


def _format_one_decimal(value: object) -> str:
    v = float(value) if value is not None else 0.0
    return f"{v:.1f}"


def _format_pct(value: object) -> str:
    """Format a 0-1 decimal as a percentage string."""
    v = float(value) if value is not None else 0.0
    return f"{v * 100:.1f}%" if v < 1 else f"{v:.1f}%"


def _format_signed_pct(value: object) -> str:
    v = float(value) if value is not None else 0.0
    return f"{v:+.0%}"


# ---------------------------------------------------------------------------
# Genome rendering — mirror of frontend/src/components/dashboard/primitives.tsx
# ::GenomeSlots so the email and the dashboard show the same labels, order,
# and image-URL normalisation. Edit both in lockstep.
# ---------------------------------------------------------------------------

_GENOME_ORDER = ["headline", "body", "image_url", "cta_text"]
_GENOME_LABELS = {
    "image_url": "image",
    "cta_text": "cta",
}
_IMG_TAG_RE = re.compile(r"IMG_[A-Za-z0-9]+")


def _slot_label(slot: str) -> str:
    return _GENOME_LABELS.get(slot, slot)


def _normalise_slot_value(slot: str, value: str) -> str:
    """Trim long slot values for display, with image_url getting special
    treatment (extract the IMG_NNN tag if present, else use the basename).

    Mirrors the ``normalize`` closure inside the dashboard's
    ``GenomeSlots`` component.
    """
    if value is None:
        return ""
    if slot == "image_url":
        match = _IMG_TAG_RE.search(value)
        if match:
            return match.group(0)
        last = value.rsplit("/", 1)[-1] if "/" in value else value
        return f"{last[:16]}…" if len(last) > 18 else last
    return f"{value[:38]}…" if len(value) > 40 else value


def _genome_pairs(genome: dict[str, str] | None) -> list[tuple[str, str]]:
    """Return ``(display_label, normalised_value)`` pairs in the dashboard's
    canonical slot order, with any extra non-canonical slots appended at
    the end. Empty / missing slots are dropped.
    """
    if not genome:
        return []
    pairs: list[tuple[str, str]] = []
    used: set[str] = set()
    for slot in _GENOME_ORDER:
        v = genome.get(slot)
        if v:
            pairs.append((_slot_label(slot), _normalise_slot_value(slot, v)))
            used.add(slot)
    # Surface any genome slots we don't have a canonical position for, so
    # new gene-pool slots aren't silently dropped.
    for slot, v in genome.items():
        if slot in used or not v:
            continue
        pairs.append((_slot_label(slot), _normalise_slot_value(slot, v)))
    return pairs


class EmailReporter:
    """Renders and sends HTML email reports via SendGrid."""

    def __init__(self, api_key: str, from_email: str, to_email: str) -> None:
        self._api_key = api_key
        self._from_email = from_email
        self._to_email = to_email
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        self._jinja_env.filters["currency"] = _format_currency
        self._jinja_env.filters["intcomma"] = _format_intcomma
        self._jinja_env.filters["onedecimal"] = _format_one_decimal
        self._jinja_env.filters["pct"] = _format_pct
        self._jinja_env.filters["signpct"] = _format_signed_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_weekly_report(
        self,
        report: WeeklyReport,
        html_content: str | None = None,
        report_type: str = "Weekly",
    ) -> bool:
        """Send a report email. Returns True on success.

        If *html_content* is not provided, the HTML is rendered from the
        Jinja2 template automatically.  *report_type* controls the subject
        line prefix (e.g. "Daily" or "Weekly").
        """
        if html_content is None:
            html_content = self._render_html(report, report_type=report_type)

        subject = (
            f"{report_type} Ad Report: {report.campaign_name} "
            f"({report.week_start.isoformat()} - {report.week_end.isoformat()})"
        )

        payload: dict[str, object] = {
            "personalizations": [
                {
                    "to": [{"email": self._to_email}],
                    "subject": subject,
                },
            ],
            "from": {"email": self._from_email},
            "content": [
                {"type": "text/html", "value": html_content},
            ],
        }

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _SENDGRID_API_URL,
                    json=payload,
                    headers=headers,
                )
                if response.status_code in (200, 202):
                    logger.info(
                        "Weekly report email sent to %s (campaign %s).",
                        self._to_email,
                        report.campaign_name,
                    )
                    return True

                logger.error(
                    "SendGrid API returned HTTP %d: %s",
                    response.status_code,
                    response.text[:500],
                )
                return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SendGrid API returned HTTP %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("SendGrid request failed: %s", exc)
            return False

    async def send_approval_digest(
        self,
        *,
        items: list[dict[str, object]],
        total: int,
        review_url: str,
    ) -> bool:
        """Send the daily approval-queue digest email.

        ``items`` is a list of ``{label, count, explainer}`` dicts —
        one row per pending ``action_type`` grouping — in the order
        the email should render them. ``total`` is the sum across all
        items, used by the subject line and headline copy.

        Template at ``src/reports/templates/approval_digest_email.html``.
        """
        template = self._jinja_env.get_template("approval_digest_email.html")
        html_content = template.render(
            items=items,
            total=total,
            review_url=review_url,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        )
        subject = (
            f"{total} pending approval"
            f"{'' if total == 1 else 's'} awaiting your review"
        )

        payload: dict[str, object] = {
            "personalizations": [
                {"to": [{"email": self._to_email}], "subject": subject},
            ],
            "from": {"email": self._from_email},
            "content": [{"type": "text/html", "value": html_content}],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _SENDGRID_API_URL, json=payload, headers=headers,
                )
                if response.status_code in (200, 202):
                    logger.info(
                        "Approval digest email sent to %s (%d pending).",
                        self._to_email,
                        total,
                    )
                    return True
                logger.error(
                    "SendGrid API returned HTTP %d: %s",
                    response.status_code,
                    response.text[:500],
                )
                return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SendGrid API returned HTTP %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("SendGrid request failed: %s", exc)
            return False

    async def send_daily_report(
        self,
        report: DailyReport,
        base_url: str = "",
        dashboard_url: str | None = None,
    ) -> bool:
        """Send a daily report email using the v2 template. Returns True on success.

        ``base_url`` is the public web-archive origin (GitHub Pages) used
        for any deep links to the static archived HTML. ``dashboard_url``
        is the authenticated dashboard deep link (e.g.
        ``https://agent.kleiber.ai/campaigns/<id>/reports/daily/<date>``)
        used by the primary "Open full report" CTA — the call site is
        expected to build this per campaign + report date.
        """
        html_content = self._render_daily_html(
            report, base_url=base_url, dashboard_url=dashboard_url
        )

        subject = f"Daily Ad Report: {report.campaign_name} ({report.report_date.isoformat()})"

        payload: dict[str, object] = {
            "personalizations": [
                {
                    "to": [{"email": self._to_email}],
                    "subject": subject,
                },
            ],
            "from": {"email": self._from_email},
            "content": [
                {"type": "text/html", "value": html_content},
            ],
        }

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _SENDGRID_API_URL,
                    json=payload,
                    headers=headers,
                )
                if response.status_code in (200, 202):
                    logger.info(
                        "Daily report email sent to %s (campaign %s, date %s).",
                        self._to_email,
                        report.campaign_name,
                        report.report_date.isoformat(),
                    )
                    return True

                logger.error(
                    "SendGrid API returned HTTP %d: %s",
                    response.status_code,
                    response.text[:500],
                )
                return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SendGrid API returned HTTP %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("SendGrid request failed: %s", exc)
            return False

    async def send_weekly_report_v2(
        self,
        report: WeeklyReport,
        campaign_name: str,
        week_label: str,
        base_url: str = "",
        review_url: str | None = None,
        dashboard_url: str | None = None,
    ) -> bool:
        """Send a weekly report email using the redesigned template. Returns True on success.

        ``dashboard_url`` is the authed weekly-report deep link
        (``{frontend_base_url}/campaigns/<id>/reports/weekly/<week_start>``);
        when provided it supersedes ``base_url`` for the primary CTA.
        """
        html_content = self._render_weekly_email_html(
            report,
            campaign_name=campaign_name,
            week_label=week_label,
            base_url=base_url,
            review_url=review_url,
            dashboard_url=dashboard_url,
        )

        subject = f"Weekly Ad Report: {campaign_name} (Week {week_label})"

        payload: dict[str, object] = {
            "personalizations": [
                {
                    "to": [{"email": self._to_email}],
                    "subject": subject,
                },
            ],
            "from": {"email": self._from_email},
            "content": [
                {"type": "text/html", "value": html_content},
            ],
        }

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _SENDGRID_API_URL,
                    json=payload,
                    headers=headers,
                )
                if response.status_code in (200, 202):
                    logger.info(
                        "Weekly report email (v2) sent to %s (campaign %s, week %s).",
                        self._to_email,
                        campaign_name,
                        week_label,
                    )
                    return True

                logger.error(
                    "SendGrid API returned HTTP %d: %s",
                    response.status_code,
                    response.text[:500],
                )
                return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SendGrid API returned HTTP %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("SendGrid request failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    def _render_daily_html(
        self,
        report: DailyReport,
        base_url: str = "",
        dashboard_url: str | None = None,
    ) -> str:
        """Render the daily email HTML from the Jinja2 template."""
        template = self._jinja_env.get_template("daily_email.html")

        return template.render(
            # Header
            campaign_name=report.campaign_name,
            report_date=report.report_date.isoformat(),
            report_date_fmt=report.report_date.strftime("%B %d, %Y"),
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
            base_url=base_url,
            dashboard_url=dashboard_url,
            day_number=report.day_number,
            cycle_number=report.cycle_number,
            # Objective-aware display lists (pre-built in the report
            # builder per the campaign's Meta objective). Templates
            # iterate these directly.
            objective=report.objective,
            headline_metrics=report.headline_metrics,
            best_variant_summary=report.best_variant_summary,
            best_variant_diagnostic_tiles=report.best_variant_diagnostic_tiles,
            variant_table_columns=report.variant_table_columns,
            # Top-line cards (legacy — left for templates we haven't
            # migrated to the data-driven loop yet).
            total_spend=report.total_spend,
            total_purchases=report.total_purchases,
            avg_cost_per_purchase=report.avg_cost_per_purchase,
            avg_roas=report.avg_roas,
            # Previous day for trends
            prev_spend=report.prev_spend,
            prev_purchases=report.prev_purchases,
            prev_avg_cpa=report.prev_avg_cpa,
            prev_avg_roas=report.prev_avg_roas,
            # Best ad spotlight
            best_variant=report.best_variant,
            best_variant_genome_pairs=(
                _genome_pairs(report.best_variant.genome)
                if report.best_variant
                else []
            ),
            best_variant_funnel=report.best_variant_funnel,
            best_variant_diagnostics=report.best_variant_diagnostics,
            best_variant_projection=report.best_variant_projection,
            # Variants table (pre-sorted, None-safe)
            variants=sorted(
                report.variants,
                key=lambda v: (v.cost_per_purchase is None, v.cost_per_purchase or 0),
            ),
            # Alerts and actions
            fatigue_alerts=report.fatigue_alerts,
            actions=report.actions,
            next_cycle=report.next_cycle,
            winners=report.winners,
        )

    def _render_weekly_email_html(
        self,
        report: WeeklyReport,
        campaign_name: str,
        week_label: str,
        base_url: str = "",
        review_url: str | None = None,
        dashboard_url: str | None = None,
    ) -> str:
        """Render the weekly email HTML from the redesigned template."""
        template = self._jinja_env.get_template("weekly_email.html")

        elements_by_hook = sorted(
            report.top_elements,
            key=lambda e: float(e.avg_hook_rate) if e.avg_hook_rate else 0,
            reverse=True,
        )

        return template.render(
            campaign_name=campaign_name,
            week_label=week_label,
            week_start=report.week_start.isoformat(),
            week_end=report.week_end.isoformat(),
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
            base_url=base_url,
            # Activity
            cycles_run=report.cycles_run,
            variants_launched=report.variants_launched,
            variants_retired=report.variants_retired,
            # Objective-aware lists (3 metric rows, summary numbers,
            # diagnostic tiles, variant-table columns).
            objective=report.objective,
            metric_rows=report.metric_rows,
            best_variant_summary=report.best_variant_summary,
            best_variant_diagnostic_tiles=report.best_variant_diagnostic_tiles,
            variant_table_columns=report.variant_table_columns,
            # Metrics
            total_impressions=report.total_impressions,
            total_reach=report.total_reach,
            total_spend=report.total_spend,
            total_purchases=report.total_purchases,
            total_purchase_value=report.total_purchase_value,
            avg_hook_rate=report.avg_hook_rate,
            avg_hold_rate=report.avg_hold_rate,
            avg_ctr=report.avg_ctr,
            avg_cpm=report.avg_cpm,
            avg_frequency=report.avg_frequency,
            avg_roas=report.avg_roas,
            avg_cost_per_purchase=report.avg_cost_per_purchase,
            # Funnel
            funnel_stages=report.funnel_stages,
            # Variants
            variants=report.all_variants,
            # Elements
            elements=report.top_elements,
            elements_by_hook=elements_by_hook,
            # Interactions
            interactions=report.top_interactions,
            # Proposed variants (weekly review flow)
            proposed_variants=report.proposed_variants,
            expired_count=report.expired_count,
            generation_paused=report.generation_paused,
            review_url=review_url or report.review_url,
            dashboard_url=dashboard_url,
        )

    def _render_html(self, report: WeeklyReport, report_type: str = "Weekly") -> str:
        """Render the report HTML from the Jinja2 template (legacy).

        Passes flat template variables as specified by the template contract.
        """
        template = self._jinja_env.get_template("weekly_report.html")

        # Build recommendation strings from the summary text.
        recommendations: list[str] = [
            line.strip().lstrip("- ").lstrip("* ")
            for line in report.summary_text.splitlines()
            if line.strip()
        ]

        # Use all_variants if populated, otherwise fall back to best/worst
        variants: list[object] = list(report.all_variants) if report.all_variants else []
        if not variants:
            if report.best_variant:
                variants.append(report.best_variant)
            if report.worst_variant:
                variants.append(report.worst_variant)

        return template.render(
            report_type=report_type,
            campaign_name=report.campaign_name,
            week_start=report.week_start.isoformat(),
            week_end=report.week_end.isoformat(),
            # Core metrics — pass as raw numbers for template formatting
            total_spend=report.total_spend,
            total_impressions=report.total_impressions,
            total_clicks=report.total_clicks,
            total_conversions=report.total_conversions,
            avg_ctr=report.avg_ctr,
            avg_cpa=report.avg_cpa,
            # Extended funnel metrics
            total_reach=report.total_reach,
            total_video_views_3s=report.total_video_views_3s,
            total_video_views_15s=report.total_video_views_15s,
            total_thruplays=report.total_thruplays,
            total_link_clicks=report.total_link_clicks,
            total_landing_page_views=report.total_landing_page_views,
            total_add_to_carts=report.total_add_to_carts,
            total_purchases=report.total_purchases,
            total_purchase_value=report.total_purchase_value,
            avg_hook_rate=report.avg_hook_rate,
            avg_hold_rate=report.avg_hold_rate,
            avg_cpm=report.avg_cpm,
            avg_frequency=report.avg_frequency,
            avg_roas=report.avg_roas,
            avg_cost_per_purchase=report.avg_cost_per_purchase,
            # Funnel stages
            funnel_stages=report.funnel_stages,
            # Activity
            cycles_run=report.cycles_run,
            variants_launched=report.variants_launched,
            variants_retired=report.variants_retired,
            # Variant data
            best_variant=report.best_variant,
            worst_variant=report.worst_variant,
            variants=variants,
            # Element + interaction data
            elements=report.top_elements,
            interactions=report.top_interactions,
            recommendations=recommendations,
        )
