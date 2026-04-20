"""Meta campaign-objective normalisation.

Meta's Campaign API returns an ``objective`` string on every campaign,
but the taxonomy has changed over time:

- **ODAX** (Outcome-Driven Ad Experiences), introduced 2022 and
  universal for campaigns created after mid-2024, uses the six
  ``OUTCOME_*`` values (``OUTCOME_SALES``, ``OUTCOME_LEADS``,
  ``OUTCOME_ENGAGEMENT``, ``OUTCOME_TRAFFIC``, ``OUTCOME_AWARENESS``,
  ``OUTCOME_APP_PROMOTION``).
- **Legacy** campaigns still return the pre-ODAX strings
  (``CONVERSIONS``, ``LINK_CLICKS``, ``LEAD_GENERATION``,
  ``POST_ENGAGEMENT``, ``BRAND_AWARENESS``, etc.).

Downstream code — the ``campaigns.objective`` column, report
builders, benchmark tables — expects a single canonical
representation. This module is the sole place that maps raw Meta
strings into the canonical set. Every caller that stores or dispatches
on an objective **must** pass the value through :func:`normalize_meta_objective`
first; the CHECK constraint on ``campaigns.objective`` enforces it at
the database boundary.

Unknown values (including anything Meta might introduce in the future
that we haven't added to the map) collapse to ``OUTCOME_UNKNOWN``;
downstream render paths treat that identically to ``OUTCOME_SALES``
(the safest fallback because every polled metric has always been
collected in that shape).
"""

from __future__ import annotations

ODAX_VALUES: frozenset[str] = frozenset(
    {
        "OUTCOME_SALES",
        "OUTCOME_LEADS",
        "OUTCOME_ENGAGEMENT",
        "OUTCOME_TRAFFIC",
        "OUTCOME_AWARENESS",
        "OUTCOME_APP_PROMOTION",
    }
)

UNKNOWN_OBJECTIVE: str = "OUTCOME_UNKNOWN"

# Legacy pre-ODAX Meta objective strings → their canonical ODAX
# equivalent. Sourced from Meta's ODAX migration guide + community
# references (Jon Loomer, Hunch, Bïrch). Keep entries alphabetical by
# key within each ODAX target so reviewers can eyeball coverage.
_LEGACY_MAP: dict[str, str] = {
    # → Sales
    "CATALOG_SALES": "OUTCOME_SALES",
    "CONVERSIONS": "OUTCOME_SALES",
    "PRODUCT_CATALOG_SALES": "OUTCOME_SALES",
    # → Leads
    "LEAD_GENERATION": "OUTCOME_LEADS",
    "MESSAGES": "OUTCOME_LEADS",
    # → Engagement
    "EVENT_RESPONSES": "OUTCOME_ENGAGEMENT",
    "PAGE_LIKES": "OUTCOME_ENGAGEMENT",
    "POST_ENGAGEMENT": "OUTCOME_ENGAGEMENT",
    "VIDEO_VIEWS": "OUTCOME_ENGAGEMENT",
    # → Traffic
    "LINK_CLICKS": "OUTCOME_TRAFFIC",
    # → Awareness
    "BRAND_AWARENESS": "OUTCOME_AWARENESS",
    "IMPRESSIONS": "OUTCOME_AWARENESS",
    "REACH": "OUTCOME_AWARENESS",
    # → App Promotion
    "APP_INSTALLS": "OUTCOME_APP_PROMOTION",
}


def normalize_meta_objective(raw: str | None) -> str:
    """Return the canonical ODAX objective for any Meta value.

    - ``None`` or empty string → ``OUTCOME_UNKNOWN``.
    - One of the six ODAX values → returned unchanged.
    - A known legacy string (see ``_LEGACY_MAP``) → the mapped ODAX value.
    - Anything else → ``OUTCOME_UNKNOWN``.

    This function is total — it never raises. Unknown values become
    the sentinel so downstream code can treat them uniformly.
    """
    if not raw:
        return UNKNOWN_OBJECTIVE
    if raw in ODAX_VALUES:
        return raw
    return _LEGACY_MAP.get(raw, UNKNOWN_OBJECTIVE)


def display_label(objective: str) -> str:
    """Human-readable short label for an objective. Used in chips / pills.

    Returned strings match the marketing copy used on the dashboard
    and in emails.
    """
    return _DISPLAY_LABELS.get(objective, "Unknown")


_DISPLAY_LABELS: dict[str, str] = {
    "OUTCOME_SALES": "Sales",
    "OUTCOME_LEADS": "Leads",
    "OUTCOME_ENGAGEMENT": "Engagement",
    "OUTCOME_TRAFFIC": "Traffic",
    "OUTCOME_AWARENESS": "Awareness",
    "OUTCOME_APP_PROMOTION": "App promotion",
    UNKNOWN_OBJECTIVE: "Unknown",
}
