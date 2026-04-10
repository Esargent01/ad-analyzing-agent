"""Self-serve campaign import flow (Phase D).

Lets a signed-in, Meta-connected user pick campaigns from their own
Meta ad account and bring them into the system. The result is:

- One new ``campaigns`` row per imported campaign, with
  ``owner_user_id = <user.id>`` and
  ``platform_campaign_id = <meta id>``.
- One new ``variants`` row per existing ad, with the genome
  reconstructed from the Meta creative (headline + body + link +
  image) so historical performance can be attributed.
- One new ``deployments`` row per ad, bridging the variant to the
  live Meta ad ID so metric polling attaches cleanly.
- Gene pool seed entries for every unique headline, body, CTA, and
  image URL encountered. Seed entries are tagged ``source="imported"``
  so they can be told apart from operator-approved values.

The 5-campaign cap (``settings.max_campaigns_per_user``) is enforced
before any writes happen. Partial failures within a bulk import are
caught per-campaign — one bad campaign doesn't roll back the others.

Exception contract:

- ``CampaignCapExceeded`` — user is already at the cap.
- ``CampaignAlreadyImported`` — this specific Meta campaign has
  been imported by this user already.
- ``MetaConnectionMissing`` / ``MetaTokenExpired`` — user needs to
  reconnect Meta before importing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.meta_factory import get_meta_adapter_for_user
from src.config import get_settings
from src.db.queries import (
    count_active_campaigns_for_user,
    get_imported_meta_campaign_ids_for_user,
)
from src.db.tables import (
    Campaign,
    Deployment,
    GenePoolEntry,
    PlatformType,
    Variant,
    VariantStatus,
)
from src.exceptions import (
    CampaignAlreadyImported,
    CampaignCapExceeded,
)
from src.models.campaigns import (
    CampaignImportOverrides,
    ImportableCampaign,
    ImportableCampaignsResponse,
    ImportedCampaignSummary,
)

logger = logging.getLogger(__name__)


# Slots that get seeded from imported ad creatives. Keep this list
# narrow — every slot here becomes a new row in the shared
# ``gene_pool`` table. Anything the generator can't later use as a
# swappable element should stay out.
_SEED_SLOTS: tuple[str, ...] = ("headline", "body", "cta_text", "image_url")


def _parse_meta_created_time(value: Any) -> datetime | None:
    """Coerce Meta's ``created_time`` string into a ``datetime``.

    Meta returns ISO 8601 with a compact (no-colon) UTC offset like
    ``'2026-04-06T14:20:59-0400'``. Python 3.11+ ``fromisoformat``
    handles this, but older runtimes and some edge cases need a
    fallback. Return ``None`` if the value is missing or unparseable
    — the field is optional on the model.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    # Python 3.11+ accepts both ``+HH:MM`` and ``+HHMM`` offsets.
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    # Older-format fallback: inject the missing colon in the offset
    # and retry (``2026-04-06T14:20:59-0400`` → ``...−04:00``).
    if len(value) >= 5 and (value[-5] in "+-") and value[-3] != ":":
        patched = f"{value[:-2]}:{value[-2:]}"
        try:
            return datetime.fromisoformat(patched)
        except ValueError:
            pass
    logger.warning("Could not parse Meta created_time: %r", value)
    return None


def _parse_meta_daily_budget(value: Any) -> float | None:
    """Coerce Meta's ``daily_budget`` (string, minor units) to a float.

    Meta returns budgets as strings denominated in the account's
    minor currency unit — e.g. USD is cents, so ``"5000"`` means
    $50.00. Divide by 100 for display. Return ``None`` if missing
    or unparseable; the model field is optional.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / 100.0
    if not isinstance(value, str) or not value:
        return None
    try:
        return float(Decimal(value)) / 100.0
    except (InvalidOperation, ValueError):
        logger.warning("Could not parse Meta daily_budget: %r", value)
        return None


async def list_importable_campaigns(
    session: AsyncSession, user_id: UUID
) -> ImportableCampaignsResponse:
    """Fetch the user's Meta campaigns and build the picker payload.

    - Fetches the user's connection and builds a fresh adapter.
    - Calls ``list_campaigns`` on the adapter.
    - Cross-references the returned Meta IDs against anything
      already imported by this user, marking duplicates.
    - Returns quota metadata alongside the list so the UI can
      render a "3/5 used" widget without a second roundtrip.
    """
    settings = get_settings()
    adapter = await get_meta_adapter_for_user(session, user_id)
    meta_campaigns_raw = await adapter.list_campaigns()

    already_imported = await get_imported_meta_campaign_ids_for_user(session, user_id)
    quota_used = await count_active_campaigns_for_user(session, user_id)
    quota_max = settings.max_campaigns_per_user

    importable = [
        ImportableCampaign(
            meta_campaign_id=str(row["meta_campaign_id"]),
            name=str(row.get("name") or "(unnamed)"),
            status=str(row.get("status") or "UNKNOWN"),
            daily_budget=_parse_meta_daily_budget(row.get("daily_budget")),
            created_time=_parse_meta_created_time(row.get("created_time")),
            objective=(str(row["objective"]) if row.get("objective") else None),
            already_imported=str(row["meta_campaign_id"]) in already_imported,
        )
        for row in meta_campaigns_raw
    ]

    return ImportableCampaignsResponse(
        importable=importable,
        quota_used=quota_used,
        quota_max=quota_max,
    )


def _extract_genome(ad: dict[str, object]) -> dict[str, str]:
    """Build a genome dict from a ``list_campaign_ads`` row.

    Only non-empty slots are populated. The caller is responsible
    for deduping genomes if it cares about uniqueness at the
    variant level; this function just flattens the ad shape.
    """
    genome: dict[str, str] = {}
    headline = str(ad.get("headline") or "").strip()
    if headline:
        genome["headline"] = headline
    body = str(ad.get("body") or "").strip()
    if body:
        genome["body"] = body
    cta = str(ad.get("cta_type") or "").strip()
    if cta:
        genome["cta_text"] = cta
    image_url = str(ad.get("image_url") or "").strip()
    if image_url:
        genome["image_url"] = image_url
    return genome


async def _seed_gene_pool_entries(
    session: AsyncSession,
    genomes: list[dict[str, str]],
) -> int:
    """Insert one gene pool row per unique (slot, value) pair.

    Uses plain SQLAlchemy ORM inserts — duplicates across
    campaigns would violate the UNIQUE constraint, so we
    pre-filter against the current set of active entries before
    inserting. Returns the number of new rows created.
    """
    # Collect unique (slot, value) pairs from every incoming genome.
    candidates: set[tuple[str, str]] = set()
    for genome in genomes:
        for slot, value in genome.items():
            if slot not in _SEED_SLOTS:
                continue
            if value:
                candidates.add((slot, value))

    if not candidates:
        return 0

    # Bulk-check which ones already exist.
    existing_stmt = select(GenePoolEntry.slot_name, GenePoolEntry.slot_value).where(
        GenePoolEntry.slot_name.in_({slot for slot, _ in candidates})
    )
    existing_rows = await session.execute(existing_stmt)
    existing: set[tuple[str, str]] = {(r[0], r[1]) for r in existing_rows}

    new_rows = 0
    for slot, value in sorted(candidates):
        if (slot, value) in existing:
            continue
        session.add(
            GenePoolEntry(
                slot_name=slot,
                slot_value=value,
                description=f"Imported from Meta ad: {value[:80]}",
                source="imported",
                is_active=True,
            )
        )
        new_rows += 1

    if new_rows:
        await session.flush()
    logger.info("Seeded %d new gene pool entries from import", new_rows)
    return new_rows


async def _next_variant_code(session: AsyncSession, campaign_id: UUID) -> str:
    """Assign the next V-code for a freshly-created campaign.

    Since the campaign was just inserted it has zero variants, so
    we always start at V1. This is a thin helper so the import
    logic stays readable and future-proof against the V-code
    numbering rules in ``db/queries.py``.
    """
    stmt = select(Variant).where(Variant.campaign_id == campaign_id)
    rows = await session.execute(stmt)
    count = len(list(rows.scalars().all()))
    return f"V{count + 1}"


async def import_campaign(
    session: AsyncSession,
    user_id: UUID,
    meta_campaign_id: str,
    overrides: CampaignImportOverrides | None = None,
) -> ImportedCampaignSummary:
    """Import a single Meta campaign into the system.

    Enforces the 5-campaign cap *before* writing anything. Creates
    the campaign + one variant + one deployment per existing ad +
    seed gene pool entries. Returns a summary; the caller is
    responsible for committing the session.
    """
    settings = get_settings()
    overrides = overrides or CampaignImportOverrides()

    # 1. Cap enforcement — fail fast before any external I/O.
    current = await count_active_campaigns_for_user(session, user_id)
    if current >= settings.max_campaigns_per_user:
        raise CampaignCapExceeded(current, settings.max_campaigns_per_user)

    # 2. Duplicate-import guard — a single user can't import the
    # same Meta campaign twice.
    already = await get_imported_meta_campaign_ids_for_user(session, user_id)
    if meta_campaign_id in already:
        raise CampaignAlreadyImported(f"Meta campaign {meta_campaign_id} is already imported.")

    # 3. Fetch Meta-side data via the per-user adapter.
    adapter = await get_meta_adapter_for_user(session, user_id)
    meta_campaigns = await adapter.list_campaigns()
    match = next(
        (c for c in meta_campaigns if str(c["meta_campaign_id"]) == meta_campaign_id),
        None,
    )
    if match is None:
        raise ValueError(f"Meta campaign {meta_campaign_id} not found in user's ad account.")

    ads = await adapter.list_campaign_ads(meta_campaign_id)

    # 4. Resolve effective settings from overrides or Meta defaults.
    meta_daily_budget = match.get("daily_budget")
    if overrides.daily_budget is not None:
        daily_budget = overrides.daily_budget
    elif isinstance(meta_daily_budget, (int, float)) and meta_daily_budget > 0:
        daily_budget = Decimal(str(meta_daily_budget))
    else:
        # Meta didn't return a campaign-level daily budget (common
        # for ABO campaigns where budgets live at the ad set). Fall
        # back to a reasonable default so the row is insertable —
        # the user can edit it later.
        daily_budget = Decimal("50.00")

    max_variants = overrides.max_concurrent_variants or settings.max_concurrent_variants
    confidence_threshold = overrides.confidence_threshold or Decimal("0.95")

    campaign = Campaign(
        name=str(match.get("name") or f"Imported {meta_campaign_id}"),
        platform=PlatformType.meta,
        platform_campaign_id=meta_campaign_id,
        daily_budget=daily_budget,
        max_concurrent_variants=max_variants,
        min_impressions_for_significance=settings.min_impressions,
        confidence_threshold=confidence_threshold,
        is_active=True,
        owner_user_id=user_id,
    )
    session.add(campaign)
    await session.flush()

    # 5. Seed gene pool from the ads' creative elements.
    genomes = [_extract_genome(ad) for ad in ads]
    genomes = [g for g in genomes if g]  # drop empty genomes
    seeded = await _seed_gene_pool_entries(session, genomes)

    # 6. One variant + one deployment per ad. Variant codes start
    # at V1 because the campaign is brand new.
    registered = 0
    for index, (ad, genome) in enumerate(zip(ads, genomes), start=1):
        if not genome:
            logger.warning(
                "Skipping ad %s in campaign %s — no extractable genome",
                ad.get("ad_id"),
                meta_campaign_id,
            )
            continue

        variant = Variant(
            campaign_id=campaign.id,
            variant_code=f"V{index}",
            genome=genome,
            status=VariantStatus.active,
            generation=0,
            parent_ids=[],
            hypothesis="Imported from existing Meta ad.",
        )
        session.add(variant)
        await session.flush()

        deployment = Deployment(
            variant_id=variant.id,
            platform=PlatformType.meta,
            platform_ad_id=str(ad["ad_id"]),
            platform_adset_id=str(ad.get("adset_id") or "") or None,
            daily_budget=daily_budget,
            is_active=(str(ad.get("status", "")).upper() == "ACTIVE"),
        )
        session.add(deployment)
        registered += 1

    await session.flush()
    logger.info(
        "Imported Meta campaign %s as %s with %d variants + %d seed pool entries",
        meta_campaign_id,
        campaign.id,
        registered,
        seeded,
    )

    return ImportedCampaignSummary(
        id=campaign.id,
        name=campaign.name,
        platform_campaign_id=meta_campaign_id,
        daily_budget=campaign.daily_budget,
        seeded_gene_pool_entries=seeded,
        registered_deployments=registered,
    )
