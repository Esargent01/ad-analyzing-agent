"""Render analysis results as static HTML report pages for GitHub Pages."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import get_settings
from src.models.reports import WeeklyReport

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["currency"] = _format_currency
    env.filters["pct"] = _format_pct
    env.filters["intcomma"] = _format_intcomma
    env.filters["signpct"] = _format_signed_pct
    env.filters["onedecimal"] = _format_one_decimal
    return env


def _format_currency(value: object) -> str:
    v = float(value) if value is not None else 0.0
    if v >= 1000:
        return f"${v:,.0f}"
    return f"${v:.2f}"


def _format_pct(value: object) -> str:
    v = float(value) if value is not None else 0.0
    return f"{v * 100:.1f}%" if v < 1 else f"{v:.1f}%"


def _format_intcomma(value: object) -> str:
    v = int(value) if value is not None else 0
    return f"{v:,}"


def _format_signed_pct(value: object) -> str:
    v = float(value) if value is not None else 0.0
    return f"{v:+.0%}"


def _format_one_decimal(value: object) -> str:
    v = float(value) if value is not None else 0.0
    return f"{v:.1f}"


def _output_dir() -> Path:
    settings = get_settings()
    return Path(settings.report_output_dir)


def render_daily_report(report: WeeklyReport, campaign_name: str, report_date: date) -> Path:
    """Render a daily report as a static HTML file.

    Reuses the WeeklyReport model since it holds all the funnel data.
    Returns the path to the generated file.
    """
    settings = get_settings()
    env = _get_jinja_env()
    template = env.get_template("daily_web.html")

    # Sort elements by hook rate for the attention ranking
    elements_by_hook = sorted(
        report.top_elements,
        key=lambda e: float(e.avg_hook_rate) if e.avg_hook_rate else 0,
        reverse=True,
    )

    has_purchases = any(v.purchases > 0 for v in report.all_variants) if report.all_variants else False

    html = template.render(
        campaign_name=campaign_name,
        report_date=report_date.isoformat(),
        report_date_fmt=report_date.strftime("%B %d, %Y"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        base_url=settings.report_base_url,
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
        avg_roas=report.avg_roas,
        avg_cost_per_purchase=report.avg_cost_per_purchase,
        # Funnel
        funnel_stages=report.funnel_stages,
        # Variants
        variants=report.all_variants,
        has_purchases=has_purchases,
        # Elements
        elements=report.top_elements,
        elements_by_hook=elements_by_hook,
        # Interactions
        interactions=report.top_interactions,
    )

    out_dir = _output_dir() / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report_date.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")

    logger.info("Daily web report written to %s", out_path)
    return out_path


def render_weekly_report(report: WeeklyReport, campaign_name: str, week_label: str) -> Path:
    """Render a weekly report as a static HTML file."""
    settings = get_settings()
    env = _get_jinja_env()
    template = env.get_template("weekly_web.html")

    elements_by_hook = sorted(
        report.top_elements,
        key=lambda e: float(e.avg_hook_rate) if e.avg_hook_rate else 0,
        reverse=True,
    )

    html = template.render(
        campaign_name=campaign_name,
        week_label=week_label,
        week_start=report.week_start.isoformat(),
        week_end=report.week_end.isoformat(),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        base_url=settings.report_base_url,
        # Activity
        cycles_run=report.cycles_run,
        variants_launched=report.variants_launched,
        variants_retired=report.variants_retired,
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
    )

    out_dir = _output_dir() / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{week_label}.html"
    out_path.write_text(html, encoding="utf-8")

    logger.info("Weekly web report written to %s", out_path)
    return out_path


def render_index(daily_dates: list[str], weekly_labels: list[str]) -> Path:
    """Render the report archive index page."""
    settings = get_settings()
    env = _get_jinja_env()
    template = env.get_template("report_index.html")

    html = template.render(
        daily_reports=sorted(daily_dates, reverse=True),
        weekly_reports=sorted(weekly_labels, reverse=True),
        base_url=settings.report_base_url,
    )

    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")

    logger.info("Report index written to %s", out_path)
    return out_path


def capture_snapshot(html_path: Path) -> Path:
    """Capture a screenshot of the .tweet-snapshot region from an HTML report.

    Uses Playwright to render the page headlessly and clip to the snapshot element.
    Returns the path to the generated PNG file.
    """
    from playwright.sync_api import sync_playwright

    png_path = html_path.with_suffix(".png")
    file_url = f"file://{html_path.resolve()}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 800, "height": 600},
            color_scheme="dark",
        )
        page.goto(file_url, wait_until="networkidle")

        snapshot_el = page.query_selector(".tweet-snapshot")
        if snapshot_el:
            snapshot_el.screenshot(path=str(png_path))
            logger.info("Snapshot captured: %s", png_path)
        else:
            # Fallback: screenshot the full page above the fold
            page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 800, "height": 600})
            logger.warning("No .tweet-snapshot element found, captured full page fallback")

        browser.close()

    return png_path
