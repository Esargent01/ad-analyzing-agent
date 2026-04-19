"""Self-serve campaign import flow (Phase D + Phase G).

Lets a signed-in, Meta-connected user pick campaigns from their own
Meta ad account and bring them into the system. The result is:

- One new ``campaigns`` row per imported campaign, with
  ``owner_user_id = <user.id>``,
  ``platform_campaign_id = <meta id>``, and Phase G's per-campaign
  tenancy columns (``meta_ad_account_id``, ``meta_page_id``,
  ``landing_page_url``) written from the user's picked values.
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

Phase G changes:

- :func:`list_importable_campaigns` now takes an optional
  ``ad_account_id``. If omitted, it falls back to the user's
  ``default_ad_account_id``; if that's also null (the user has >1
  account and hasn't picked one), raises
  :class:`MultipleAdAccountsNoDefault` so the UI can prompt.
- :func:`import_campaign` now requires ``ad_account_id`` + ``page_id``
  on every call. Both are validated against the user's enumerated
  ``available_ad_accounts`` / ``available_pages`` allowlist to block
  cross-user injection.
- Neither function goes through :mod:`src.adapters.meta_factory`
  anymore — the factory is designed around resolved per-campaign
  values, but during the *import* flow the campaign row doesn't
  exist yet. We construct the adapter directly here using the
  user's decrypted token.

Exception contract:

- ``CampaignCapExceeded`` — user is already at the cap.
- ``CampaignAlreadyImported`` — this specific Meta campaign has
  been imported by this user already.
- ``MetaConnectionMissing`` / ``MetaTokenExpired`` — user needs to
  reconnect Meta before importing.
- ``MultipleAdAccountsNoDefault`` — Phase G, user has >1 account
  and no default; UI must prompt for a choice.
- ``AdAccountNotAllowed`` — Phase G, submitted account or Page ID
  isn't in the user's allowlist.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.meta import MetaAdapter
from src.config import get_settings
from src.dashboard.crypto import decrypt_token
from src.db.queries import (
    count_active_campaigns_for_user,
    get_imported_meta_campaign_ids_for_user,
    get_meta_connection,
    grant_user_campaign_access,
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
    AdAccountNotAllowed,
    CampaignAlreadyImported,
    CampaignCapExceeded,
    MetaConnectionMissing,
    MetaTokenExpired,
    MultipleAdAccountsNoDefault,
)
from src.models.campaigns import (
    CampaignImportOverrides,
    ImportableCampaign,
    ImportableCampaignsResponse,
    ImportedCampaignSummary,
)
from src.models.oauth import MetaAdAccountInfo, MetaPageInfo

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
    """Coerce Meta's ``daily_budget`` into a float in major units.

    ``MetaAdapter.list_campaigns`` already normalises Meta's raw
    minor-unit string (e.g. USD cents like ``"5000"``) into a
    major-unit float (``50.0``) before the payload reaches this
    service, so the happy path here is a numeric passthrough.
    Strings are still accepted defensively — parsed as dollars,
    not cents — in case a future adapter or a test fake hands us
    the raw Meta payload. Return ``None`` if the input is missing
    or unparseable; the model field is optional.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return float(Decimal(value))
    except (InvalidOperation, ValueError):
        logger.warning("Could not parse Meta daily_budget: %r", value)
        return None


def _coerce_available_ad_accounts(
    raw: list[dict] | None,
) -> list[MetaAdAccountInfo]:
    """Best-effort-parse the JSONB column into Pydantic models."""
    out: list[MetaAdAccountInfo] = []
    for item in raw or []:
        try:
            out.append(MetaAdAccountInfo.model_validate(item))
        except Exception:  # noqa: BLE001
            logger.warning("Skipping malformed available_ad_accounts row: %r", item)
    return out


def _coerce_available_pages(raw: list[dict] | None) -> list[MetaPageInfo]:
    out: list[MetaPageInfo] = []
    for item in raw or []:
        try:
            out.append(MetaPageInfo.model_validate(item))
        except Exception:  # noqa: BLE001
            logger.warning("Skipping malformed available_pages row: %r", item)
    return out


async def _build_user_adapter(
    session: AsyncSession,
    user_id: UUID,
    ad_account_id: str,
    page_id: str = "",
    landing_page_url: str | None = None,
) -> MetaAdapter:
    """Construct a per-request MetaAdapter for the import flow.

    Unlike :mod:`src.adapters.meta_factory`, this helper is used
    *during* the import flow — before a ``campaigns`` row exists to
    read per-campaign values off. The caller passes the user's
    picked ``ad_account_id`` (and optionally ``page_id`` /
    ``landing_page_url``); this function fetches the connection,
    checks expiry, and builds a fresh adapter.

    Raises the same exceptions as the factory:
    ``MetaConnectionMissing`` / ``MetaTokenExpired``.
    """
    connection = await get_meta_connection(session, user_id)
    if connection is None:
        raise MetaConnectionMissing(f"User {user_id} has not connected a Meta account.")
    if connection.token_expires_at is not None:
        now = datetime.now(UTC)
        if connection.token_expires_at <= now:
            raise MetaTokenExpired(
                f"User {user_id}'s Meta token expired at "
                f"{connection.token_expires_at.isoformat()} — "
                "they need to reconnect."
            )

    plaintext_token = decrypt_token(connection.encrypted_access_token)
    settings = get_settings()
    return MetaAdapter(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        access_token=plaintext_token,
        ad_account_id=ad_account_id,
        page_id=page_id,
        landing_page_url=landing_page_url or "",
    )


async def list_importable_campaigns(
    session: AsyncSession,
    user_id: UUID,
    ad_account_id: str | None = None,
) -> ImportableCampaignsResponse:
    """Fetch the user's Meta campaigns and build the picker payload.

    - Fetches the user's connection + enumerated assets.
    - Resolves the effective ``ad_account_id``: explicit arg wins,
      else ``default_ad_account_id`` from the connection row, else
      raise :class:`MultipleAdAccountsNoDefault` so the UI prompts.
    - Constructs a fresh adapter scoped to that account and calls
      ``list_campaigns``.
    - Cross-references the returned Meta IDs against anything
      already imported by this user, marking duplicates.
    - Returns quota metadata + the user's full account/Page lists
      alongside the campaigns so the UI can render the picker and
      account dropdown from a single roundtrip.
    """
    settings = get_settings()
    connection = await get_meta_connection(session, user_id)
    if connection is None:
        raise MetaConnectionMissing(f"User {user_id} has not connected a Meta account.")

    accounts = _coerce_available_ad_accounts(connection.available_ad_accounts)
    pages = _coerce_available_pages(connection.available_pages)

    # Resolve the effective ad account. Explicit arg wins; otherwise
    # fall back to the user's default; otherwise we can't proceed.
    effective_account = ad_account_id or connection.default_ad_account_id
    if effective_account is None:
        if len(accounts) == 0:
            # Edge case: brand-new Facebook account with no reachable
            # ad accounts at all. Return an empty picker with context
            # so the UI can show an actionable "create one in Meta Ads
            # Manager first" message instead of an error toast.
            return ImportableCampaignsResponse(
                importable=[],
                quota_used=await count_active_campaigns_for_user(session, user_id),
                quota_max=settings.max_campaigns_per_user,
                available_ad_accounts=accounts,
                available_pages=pages,
                default_ad_account_id=connection.default_ad_account_id,
                default_page_id=connection.default_page_id,
                selected_ad_account_id=None,
            )
        raise MultipleAdAccountsNoDefault(
            f"User {user_id} has {len(accounts)} ad accounts and no default set. "
            "Pick one on the import page before fetching campaigns."
        )

    # Defence-in-depth: never build an adapter for an account the
    # user's own token couldn't have enumerated. In practice Meta
    # would reject the call anyway, but a clean 400 is friendlier.
    if accounts and effective_account not in {a.id for a in accounts}:
        raise AdAccountNotAllowed(
            f"Ad account {effective_account} is not in user {user_id}'s allowlist."
        )

    adapter = await _build_user_adapter(session, user_id, ad_account_id=effective_account)
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
        available_ad_accounts=accounts,
        available_pages=pages,
        default_ad_account_id=connection.default_ad_account_id,
        default_page_id=connection.default_page_id,
        selected_ad_account_id=effective_account,
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


def _extract_asset_feed_pool_entries(ad: dict[str, object]) -> list[dict[str, str]]:
    """Flatten Dynamic-Creative asset-feed variants into pseudo-genomes.

    Meta's Dynamic Creative (Advantage+) format stores multiple
    titles, bodies, and CTAs in ``asset_feed_spec`` — Meta shuffles
    them at delivery time. ``_extract_genome`` only picks the first
    of each for the canonical variant. This helper returns one
    single-slot pseudo-genome per remaining variant so the caller
    can feed them into ``_seed_gene_pool_entries`` and grow the pool
    with every headline/body/CTA the advertiser already wrote.

    Returns an empty list for non-Dynamic-Creative ads. Single-slot
    pseudo-genomes are intentional: the gene-pool seeder reads
    ``(slot, value)`` pairs independently so one slot per dict works
    the same as combining them, and keeps the code branch-free.
    """
    extras: list[dict[str, str]] = []
    titles = ad.get("asset_feed_titles") or []
    bodies = ad.get("asset_feed_bodies") or []
    cta_types = ad.get("asset_feed_cta_types") or []
    if isinstance(titles, list):
        for t in titles:
            t = (t or "").strip() if isinstance(t, str) else ""
            if t:
                extras.append({"headline": t})
    if isinstance(bodies, list):
        for b in bodies:
            b = (b or "").strip() if isinstance(b, str) else ""
            if b:
                extras.append({"body": b})
    if isinstance(cta_types, list):
        for c in cta_types:
            c = (c or "").strip() if isinstance(c, str) else ""
            if c:
                extras.append({"cta_text": c})
    return extras


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
    ad_account_id: str,
    page_id: str,
    landing_page_url: str | None = None,
    overrides: CampaignImportOverrides | None = None,
) -> ImportedCampaignSummary:
    """Import a single Meta campaign into the system.

    Enforces the 5-campaign cap *before* writing anything. Creates
    the campaign + one variant + one deployment per existing ad +
    seed gene pool entries. Returns a summary; the caller is
    responsible for committing the session.

    Phase G made ``ad_account_id`` and ``page_id`` required: they're
    validated against the user's ``available_ad_accounts`` /
    ``available_pages`` allowlist (the security backstop against a
    malicious client passing another user's account ID) and then
    persisted on the new ``campaigns`` row so the cron can resolve
    them without touching settings.
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

    # 3. Cross-user allowlist check (Phase G). Reject if either ID
    # isn't in the user's enumerated assets — this is the backstop
    # against a client POSTing another user's account or Page id.
    connection = await get_meta_connection(session, user_id)
    if connection is None:
        raise MetaConnectionMissing(f"User {user_id} has not connected a Meta account.")
    account_ids = {a["id"] for a in connection.available_ad_accounts or []}
    page_ids = {p["id"] for p in connection.available_pages or []}
    if account_ids and ad_account_id not in account_ids:
        raise AdAccountNotAllowed(
            f"Ad account {ad_account_id} is not in user {user_id}'s allowlist."
        )
    if page_ids and page_id not in page_ids:
        raise AdAccountNotAllowed(f"Page {page_id} is not in user {user_id}'s allowlist.")

    # 4. Fetch Meta-side data via a per-request adapter scoped to the
    # chosen account.
    adapter = await _build_user_adapter(
        session,
        user_id,
        ad_account_id=ad_account_id,
        page_id=page_id,
        landing_page_url=landing_page_url,
    )
    meta_campaigns = await adapter.list_campaigns()
    match = next(
        (c for c in meta_campaigns if str(c["meta_campaign_id"]) == meta_campaign_id),
        None,
    )
    if match is None:
        raise ValueError(f"Meta campaign {meta_campaign_id} not found in user's ad account.")

    ads = await adapter.list_campaign_ads(meta_campaign_id)

    # 5. Resolve effective settings from overrides or Meta defaults.
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
        meta_ad_account_id=ad_account_id,
        meta_page_id=page_id,
        landing_page_url=landing_page_url,
    )
    session.add(campaign)
    await session.flush()

    # Grant the importer dashboard access. ``campaigns.owner_user_id``
    # alone is not sufficient — the dashboard's ``require_campaign_access``
    # dependency scopes every ``/api/campaigns/{id}/...`` endpoint
    # against the ``user_campaigns`` join table so the same permission
    # model works for both the owner and any later-shared collaborators.
    # Skipping this step hides the freshly-imported campaign from its
    # own creator with a 404 on daily/weekly/experimental routes.
    await grant_user_campaign_access(
        session, user_id=user_id, campaign_id=campaign.id
    )

    # 5. Seed gene pool from the ads' creative elements. For
    # Dynamic-Creative ads (``asset_feed_spec``), the canonical
    # ``_extract_genome`` only picks the first asset in each slot —
    # ``_extract_asset_feed_pool_entries`` supplies the remainder so
    # every headline/body/CTA the advertiser authored is available to
    # the generator, not just the one we picked as canonical.
    genomes = [_extract_genome(ad) for ad in ads]
    genomes = [g for g in genomes if g]
    asset_feed_extras: list[dict[str, str]] = []
    for ad in ads:
        asset_feed_extras.extend(_extract_asset_feed_pool_entries(ad))
    seeded = await _seed_gene_pool_entries(session, genomes + asset_feed_extras)

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
            # Meta-reported creative format (VIDEO/PHOTO/SHARE/
            # MULTI_SHARE) mapped into our taxonomy by the adapter.
            # Reports read this to hide hook/hold/3s/15s for image
            # ads. Fall through to "unknown" — the renderers treat
            # that identically to video/mixed (full funnel) so an
            # unexpected creative type can't break the report.
            media_type=str(ad.get("media_type") or "unknown"),
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
