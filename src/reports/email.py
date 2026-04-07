"""Weekly email reporter: renders HTML via Jinja2, sends via SendGrid API."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import jinja2

from src.models.reports import WeeklyReport

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailReporter:
    """Renders and sends weekly HTML email reports via SendGrid."""

    def __init__(self, api_key: str, from_email: str, to_email: str) -> None:
        self._api_key = api_key
        self._from_email = from_email
        self._to_email = to_email
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_weekly_report(
        self,
        report: WeeklyReport,
        html_content: str | None = None,
    ) -> bool:
        """Send the weekly report email. Returns True on success.

        If *html_content* is not provided, the HTML is rendered from the
        Jinja2 template automatically.
        """
        if html_content is None:
            html_content = self._render_html(report)

        subject = (
            f"Weekly Ad Report: {report.campaign_name} "
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

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    def _render_html(self, report: WeeklyReport) -> str:
        """Render the weekly report HTML from the Jinja2 template.

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
