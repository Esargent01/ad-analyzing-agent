"""Render analysis results as static HTML report pages for GitHub Pages."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import get_settings
from src.models.reports import DailyReport, WeeklyReport

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


def _sort_variants_by_cpa(variants: list) -> list:
    """Sort variants by cost_per_purchase, None values last."""
    return sorted(variants, key=lambda v: (v.cost_per_purchase is None, v.cost_per_purchase or 0))


def _output_dir() -> Path:
    settings = get_settings()
    return Path(settings.report_output_dir)


def render_daily_report_v2(report: DailyReport) -> Path:
    """Render the redesigned daily report with best-ad spotlight.

    Uses the new DailyReport model and daily_web.html template.
    Returns the path to the generated file.
    """
    settings = get_settings()
    env = _get_jinja_env()
    template = env.get_template("daily_web.html")

    html = template.render(
        # Header
        campaign_name=report.campaign_name,
        report_date=report.report_date.isoformat(),
        report_date_fmt=report.report_date.strftime("%B %d, %Y"),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        base_url=settings.report_base_url,
        day_number=report.day_number,
        cycle_number=report.cycle_number,
        # Top-line cards
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
        best_variant_funnel=report.best_variant_funnel,
        best_variant_diagnostics=report.best_variant_diagnostics,
        best_variant_projection=report.best_variant_projection,
        # Variants table (pre-sorted, None-safe)
        variants=_sort_variants_by_cpa(report.variants),
        # Alerts and actions
        fatigue_alerts=report.fatigue_alerts,
        actions=report.actions,
        next_cycle=report.next_cycle,
        winners=report.winners,
    )

    out_dir = _output_dir() / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.report_date.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")

    logger.info("Daily web report (v2) written to %s", out_path)
    return out_path


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

    has_purchases = (
        any(v.purchases > 0 for v in report.all_variants) if report.all_variants else False
    )

    html = template.render(
        campaign_name=campaign_name,
        report_date=report_date.isoformat(),
        report_date_fmt=report_date.strftime("%B %d, %Y"),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
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
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
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
        # Proposed variants (weekly review flow)
        proposed_variants=report.proposed_variants,
        expired_count=report.expired_count,
        generation_paused=report.generation_paused,
        review_url=report.review_url,
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
