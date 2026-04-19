"""Report builder — pure functions for constructing report data.

No database access, no async. Takes domain objects, returns report models.
"""

from __future__ import annotations

from src.models.reports import (
    Diagnostic,
    ReportFunnelStage,
    VariantReport,
)


def build_funnel(v: VariantReport) -> list[ReportFunnelStage]:
    """Build funnel stages for a variant.

    Image ads (``v.media_type == "image"``) skip the 3s/15s video-view
    stages since they'd always be zero and misleading. Video, mixed
    (carousel), and unknown keep the full funnel — unknown is the safe
    default for variants that predate the ``media_type`` column.
    """
    stages = []
    prev_count = v.impressions

    is_image_only = v.media_type == "image"

    steps = [
        ("Impressions", v.impressions, 100.0, "", "#534AB7"),
    ]
    if not is_image_only:
        steps.extend(
            [
                ("3s views", v.video_views_3s, v.hook_rate_pct, "hook rate", "#7F77DD"),
                ("15s views", v.video_views_15s, v.hold_rate_pct, "hold rate", "#378ADD"),
            ]
        )
    steps.extend(
        [
            ("Link clicks", v.link_clicks, v.ctr_pct, "CTR", "#1D9E75"),
            ("Add to carts", v.add_to_carts, v.atc_rate_pct, "ATC rate", "#639922"),
            ("Purchases", v.purchases, v.checkout_rate_pct, "checkout rate", "#27500A"),
        ]
    )

    for label, count, rate, rate_label, color in steps:
        dropoff = ((prev_count - count) / prev_count * 100) if prev_count > 0 else 0
        stages.append(
            ReportFunnelStage(
                label=label,
                count=count,
                rate_pct=round(rate, 1),
                rate_label=rate_label,
                dropoff_pct=round(dropoff, 0),
                bar_color=color,
            )
        )
        prev_count = count  # 0 is fine — next iteration's guard handles it

    return stages


def build_diagnostics(v: VariantReport) -> list[Diagnostic]:
    """Generate diagnostic observations for a variant.

    Hook rate and hold rate diagnostics are skipped for image ads — they
    measure video-watching behavior that doesn't exist for static
    creatives, and the "below 25% floor" template would read as
    nonsensical commentary on a still image. Video / mixed / unknown
    media types keep the full diagnostic set.
    """
    diags: list[Diagnostic] = []

    # Hook and hold rates only apply to video-ish creatives. Skip the
    # entire block for image-only ads; video/mixed/unknown run it.
    if v.media_type != "image":
        # Hook rate
        if v.hook_rate_pct >= 30:
            diags.append(
                Diagnostic(
                    text=f"Hook rate {v.hook_rate_pct:.0f}% — strong opener, above 30% benchmark",
                    severity="good",
                )
            )
        elif v.hook_rate_pct >= 25:
            diags.append(
                Diagnostic(
                    text=f"Hook rate {v.hook_rate_pct:.0f}% — acceptable but below 30% target",
                    severity="warning",
                )
            )
        else:
            diags.append(
                Diagnostic(
                    text=f"Hook rate {v.hook_rate_pct:.0f}% — below 25% floor, creative isn't stopping the scroll",
                    severity="bad",
                )
            )

        # Hold rate
        if v.hold_rate_pct >= 25:
            diags.append(
                Diagnostic(
                    text=f"Hold rate {v.hold_rate_pct:.0f}% — narrative keeps viewers engaged past 15 seconds",
                    severity="good",
                )
            )
        else:
            diags.append(
                Diagnostic(
                    text=f"Hold rate {v.hold_rate_pct:.0f}% — viewers lose interest after the hook. Mid-video content needs work.",
                    severity="warning" if v.hold_rate_pct >= 15 else "bad",
                )
            )

    # ATC rate
    if v.atc_rate_pct >= 5:
        diags.append(
            Diagnostic(
                text=f"ATC rate {v.atc_rate_pct:.0f}% — landing page conversion is healthy (benchmark: 5-10%)",
                severity="good",
            )
        )
    else:
        diags.append(
            Diagnostic(
                text=f"ATC rate {v.atc_rate_pct:.0f}% — below 5% benchmark. Ad may promise something the landing page doesn't deliver.",
                severity="bad",
            )
        )

    # Checkout rate
    if v.checkout_rate_pct >= 30:
        diags.append(
            Diagnostic(
                text=f"Checkout rate {v.checkout_rate_pct:.0f}% — checkout process is healthy",
                severity="good",
            )
        )
    elif v.checkout_rate_pct > 0:
        diags.append(
            Diagnostic(
                text=f"Checkout rate {v.checkout_rate_pct:.0f}% — below 30% benchmark. Potential friction at payment/shipping.",
                severity="warning" if v.checkout_rate_pct >= 20 else "bad",
            )
        )

    # Frequency
    if v.frequency > 3.0:
        diags.append(
            Diagnostic(
                text=f"Frequency {v.frequency:.1f} — above 3.0, audience seeing the ad too often",
                severity="bad",
            )
        )
    elif v.frequency > 2.5:
        diags.append(
            Diagnostic(
                text=f"Frequency {v.frequency:.1f} — approaching fatigue threshold of 3.0",
                severity="warning",
            )
        )

    return diags


def build_projection(v: VariantReport) -> str | None:
    """Generate improvement projection based on weakest funnel stage.

    Image-only ads drop the hook/hold stages from consideration —
    they'd always be zero and falsely rank as the "weakest stage",
    suppressing otherwise-valid projections from ATC rate or
    checkout rate.
    """
    if v.purchases == 0 or v.cost_per_purchase is None:
        return None

    stages = {
        "checkout_rate_pct": (v.checkout_rate_pct, 30.0, "checkout rate"),
        "atc_rate_pct": (v.atc_rate_pct, 10.0, "ATC rate"),
    }
    if v.media_type != "image":
        stages["hook_rate_pct"] = (v.hook_rate_pct, 30.0, "hook rate")
        stages["hold_rate_pct"] = (v.hold_rate_pct, 25.0, "hold rate")

    weakest = None
    worst_gap = 0.0
    for key, (actual, benchmark, label) in stages.items():
        gap = (benchmark - actual) / benchmark if benchmark > 0 else 0
        if gap > worst_gap:
            worst_gap = gap
            weakest = (key, actual, benchmark, label)

    if weakest is None or worst_gap <= 0:
        return None

    key, actual, benchmark, label = weakest

    if key == "checkout_rate_pct" and v.add_to_carts > 0:
        projected_purchases = round(v.add_to_carts * (benchmark / 100))
        if projected_purchases > 0:
            projected_cpa = float(v.spend) / projected_purchases
            improvement = (v.cost_per_purchase - projected_cpa) / v.cost_per_purchase * 100
            return (
                f"If {label} improved to {benchmark:.0f}%, this ad would produce "
                f"{projected_purchases} purchases at ${projected_cpa:.2f} CPA — "
                f"a {improvement:.0f}% improvement with zero creative changes."
            )
    elif key == "atc_rate_pct" and v.link_clicks > 0:
        projected_atc = round(v.link_clicks * (benchmark / 100))
        checkout = v.checkout_rate_pct / 100 if v.checkout_rate_pct > 0 else 0.3
        projected_purchases = round(projected_atc * checkout)
        if projected_purchases > 0:
            projected_cpa = float(v.spend) / projected_purchases
            return (
                f"If {label} improved to {benchmark:.0f}%, projected "
                f"{projected_purchases} purchases at ${projected_cpa:.2f} CPA."
            )

    return None


def select_best_variant(variants: list[VariantReport]) -> VariantReport | None:
    """Select the best-performing variant for the spotlight.

    Rules:
    1. Must have at least 3 purchases (enough data to be meaningful)
    2. Lowest cost per purchase wins
    3. Ties broken by ROAS (higher wins)
    """
    eligible = [v for v in variants if v.purchases >= 3 and v.cost_per_purchase is not None]
    if not eligible:
        # Fall back to most purchases if none hit threshold
        with_purchases = [
            v for v in variants if v.purchases > 0 and v.cost_per_purchase is not None
        ]
        if with_purchases:
            return min(with_purchases, key=lambda v: (v.cost_per_purchase, -(v.roas or 0)))
        # Final fallback: variant with most impressions
        if variants:
            return max(variants, key=lambda v: v.impressions)
        return None
    return min(eligible, key=lambda v: (v.cost_per_purchase, -(v.roas or 0)))
