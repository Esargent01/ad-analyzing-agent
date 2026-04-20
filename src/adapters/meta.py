"""Meta (Facebook) Marketing API adapter.

Uses the ``facebook-business`` SDK for ad management and metrics retrieval.
All external calls are wrapped with error handling that converts
``FacebookRequestError`` into ``PlatformAPIError``.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adimage import AdImage
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.advideo import AdVideo
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError

from src.adapters.base import AdMetrics, BaseAdapter, MediaAsset
from src.adapters.meta_objective import normalize_meta_objective
from src.exceptions import PlatformAPIError

logger = logging.getLogger(__name__)


_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 2.0  # seconds


# Mapping from Meta's ``AdCreative.object_type`` enum to our internal
# media-type taxonomy. Source of truth: Meta's Marketing API AdCreative
# reference. Values we don't explicitly map fall through to ``"unknown"``
# so reports render the full funnel as a safe default.
_META_OBJECT_TYPE_MAP: dict[str, str] = {
    "VIDEO": "video",
    "PHOTO": "image",
    "SHARE": "image",        # link-share creative (image + link preview)
    "MULTI_SHARE": "mixed",  # carousel — cards can be image or video
}


def _map_media_type(object_type: str | None) -> str:
    """Translate Meta's ``AdCreative.object_type`` into our taxonomy.

    Returns one of ``"video"``, ``"image"``, ``"mixed"``, or ``"unknown"``.
    Unknown covers unmapped values (``"STATUS"``, ``"OFFER"``,
    ``"INVALID"``) and missing data — callers treat unknown identically
    to video/mixed (i.e. show all funnel stages) so this always-safe
    fallback preserves pre-existing behavior for anything surprising.
    """
    if not object_type:
        return "unknown"
    return _META_OBJECT_TYPE_MAP.get(object_type, "unknown")


class MetaAdapter(BaseAdapter):
    """Meta Marketing API adapter.

    The ``facebook-business`` SDK is synchronous, so all SDK calls
    are dispatched to a thread-pool executor via ``asyncio.to_thread``
    to keep the event loop free.

    **Tokens AND ad account / Page IDs are per-campaign and short-lived.**
    After Phase C the access token is always the decrypted long-lived
    token of a single app user (never a global operator token); after
    Phase G the ``ad_account_id``, ``page_id`` and ``landing_page_url``
    are also per-campaign values, read off the ``campaigns`` row by
    :func:`src.adapters.meta_factory.get_meta_adapter_for_campaign`.
    None of the three come from global settings anymore.

    Construct a fresh ``MetaAdapter`` at the start of each cycle via
    :mod:`src.adapters.meta_factory` and discard it when the cycle
    ends. Never cache an instance across users or across cycles —
    ``FacebookAdsApi.init`` mutates process-global SDK state, and
    cached instances will silently leak token identity across
    concurrent users.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        access_token: str,
        ad_account_id: str,
        page_id: str = "",
        landing_page_url: str = "https://example.com",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._access_token = access_token
        self._ad_account_id = ad_account_id
        self._page_id = page_id
        self._landing_page_url = landing_page_url
        self._image_hash_cache: dict[str, str] = {}  # image_url -> hash

        # Initialise the SDK globally (idempotent).
        FacebookAdsApi.init(app_id, app_secret, access_token)
        self._account = AdAccount(ad_account_id)
        logger.info("MetaAdapter initialised for account %s (page %s)", ad_account_id, page_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_sync(self, fn: partial[object]) -> object:
        """Run a synchronous SDK call in a thread with retry + backoff."""
        last_error: FacebookRequestError | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await asyncio.to_thread(fn)
            except FacebookRequestError as exc:
                last_error = exc
                # Rate-limit errors: code 17 or 32
                if exc.api_error_code() in (17, 32, 4):
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Meta rate limit hit (attempt %d/%d), backing off %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    # Non-retryable error — raise immediately
                    raise self._wrap_error(exc) from exc

        # Exhausted retries
        assert last_error is not None
        raise self._wrap_error(last_error) from last_error

    @staticmethod
    def _wrap_error(exc: FacebookRequestError) -> PlatformAPIError:
        """Convert a Facebook SDK error into a ``PlatformAPIError``."""
        return PlatformAPIError(
            platform="meta",
            message=f"API error {exc.api_error_code()}: {exc.api_error_message()}",
            response_body=str(exc.body()),
        )

    async def _upload_image(self, hero_style: str) -> str:
        """Generate a placeholder PNG for *hero_style*, upload to Meta, return image hash.

        Results are cached so the same style is only uploaded once per
        adapter lifetime.
        """
        if hero_style in self._image_hash_cache:
            return self._image_hash_cache[hero_style]

        import struct
        import tempfile
        import zlib

        # Color per hero style (R, G, B)
        colors: dict[str, tuple[int, int, int]] = {
            "lifestyle_photo": (76, 175, 80),
            "product_shot": (33, 150, 243),
            "abstract_graphic": (156, 39, 176),
            "testimonial_card": (255, 152, 0),
            "before_after": (244, 67, 54),
        }
        r, g, b = colors.get(hero_style, (96, 125, 139))

        def _create_and_upload() -> str:
            # Generate a minimal 1200x628 PNG (solid color) using raw PNG encoding
            width, height = 1200, 628
            raw_rows = b""
            for _ in range(height):
                raw_rows += b"\x00" + bytes([r, g, b]) * width

            def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
                chunk = chunk_type + data
                return (
                    struct.pack(">I", len(data))
                    + chunk
                    + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
                )

            ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
            png = b"\x89PNG\r\n\x1a\n"
            png += _png_chunk(b"IHDR", ihdr_data)
            png += _png_chunk(b"IDAT", zlib.compress(raw_rows))
            png += _png_chunk(b"IEND", b"")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(png)
                tmp_path = tmp.name

            # Upload to Meta
            image = AdImage(parent_id=self._ad_account_id)
            image[AdImage.Field.filename] = tmp_path
            image.remote_create()

            import os

            os.unlink(tmp_path)

            return str(image[AdImage.Field.hash])

        image_hash: str = await self._run_sync(partial(_create_and_upload))  # type: ignore[assignment]
        self._image_hash_cache[hero_style] = image_hash
        logger.info("Uploaded placeholder image for '%s' → hash %s", hero_style, image_hash)
        return image_hash

    def _build_creative_params(
        self,
        variant_code: str,
        genome: dict[str, str],
        image_hash: str,
    ) -> dict[str, object]:
        """Map a creative genome to Meta ad creative parameters."""
        headline = genome.get("headline", "")
        subhead = genome.get("subhead", "")
        cta_text = genome.get("cta_text", "")

        # Meta CTA types mapped from genome values
        cta_map: dict[str, str] = {
            "Claim my discount": "GET_OFFER",
            "Shop now": "SHOP_NOW",
            "Learn more": "LEARN_MORE",
            "Sign up free": "SIGN_UP",
            "Start my trial": "SIGN_UP",
            "Get started": "LEARN_MORE",
        }
        cta_type = cta_map.get(cta_text, "LEARN_MORE")

        return {
            "name": f"AdAgent {variant_code}",
            "object_story_spec": {
                "page_id": self._page_id,
                "link_data": {
                    "link": self._landing_page_url,
                    "message": subhead,
                    "name": headline,
                    "description": f"Creative variant {variant_code}",
                    "call_to_action": {
                        "type": cta_type,
                        "value": {"link": self._landing_page_url},
                    },
                    "image_hash": image_hash,
                },
            },
        }

    # ------------------------------------------------------------------
    # BaseAdapter implementation
    # ------------------------------------------------------------------

    async def create_ad(
        self,
        campaign_id: str,
        variant_code: str,
        genome: dict[str, str],
        daily_budget: float,
        media_info: dict[str, str] | None = None,
        audience_meta: dict | None = None,
    ) -> str:
        """Create a Meta ad inside *campaign_id*.

        Args:
            campaign_id: Meta campaign ID.
            variant_code: Human-readable variant code.
            genome: Creative genome dict.
            daily_budget: Daily spend cap in dollars.
            media_info: Optional dict with ``asset_type`` ("image"/"video")
                and ``platform_id`` (image hash or video ID) to use real
                media instead of a placeholder.

        Steps:
        1. Create an ``AdCreative`` from the genome.
        2. Create an ``AdSet`` with the daily budget.
        3. Create an ``Ad`` linking creative + ad set.
        """
        logger.info("Creating Meta ad for %s in campaign %s", variant_code, campaign_id)

        # 0. Resolve media asset — real asset or placeholder fallback
        if media_info and media_info.get("asset_type") == "video":
            # Video creative — use video_data path
            creative_params = self._build_video_creative_params(
                variant_code,
                genome,
                video_id=media_info["platform_id"],
                thumbnail_hash=media_info.get("thumbnail_hash"),
            )
        elif media_info and media_info.get("asset_type") == "image":
            # Real image — use the hash directly, no upload needed
            image_hash = media_info["platform_id"]
            creative_params = self._build_creative_params(variant_code, genome, image_hash)
        else:
            # Fallback: generate a placeholder PNG from media_asset name
            style_key = genome.get("media_asset", "lifestyle_photo")
            image_hash = await self._upload_image(style_key)
            creative_params = self._build_creative_params(variant_code, genome, image_hash)

        def _create_creative() -> str:
            creative = self._account.create_ad_creative(params=creative_params)
            return str(creative["id"])

        creative_id: str = await self._run_sync(partial(_create_creative))  # type: ignore[assignment]

        # 2. Ad Set
        adset_params = {
            "name": f"AdAgent AdSet {variant_code}",
            "campaign_id": campaign_id,
            "daily_budget": int(daily_budget * 100),  # Meta uses cents
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LINK_CLICKS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "status": "ACTIVE",
            "targeting": self._build_targeting(genome, audience_meta=audience_meta),
        }

        def _create_adset() -> str:
            adset = self._account.create_ad_set(params=adset_params)
            return str(adset["id"])

        adset_id: str = await self._run_sync(partial(_create_adset))  # type: ignore[assignment]

        # 3. Ad
        ad_params = {
            "name": f"AdAgent Ad {variant_code}",
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "ACTIVE",
        }

        def _create_ad() -> str:
            ad = self._account.create_ad(params=ad_params)
            return str(ad["id"])

        ad_id: str = await self._run_sync(partial(_create_ad))  # type: ignore[assignment]
        logger.info("Created Meta ad %s (creative=%s, adset=%s)", ad_id, creative_id, adset_id)
        return ad_id

    async def pause_ad(self, platform_ad_id: str) -> bool:
        logger.info("Pausing Meta ad %s", platform_ad_id)

        def _pause() -> bool:
            ad = Ad(platform_ad_id)
            ad.api_update(params={"status": Ad.Status.paused})
            return True

        result: bool = await self._run_sync(partial(_pause))  # type: ignore[assignment]
        return result

    async def resume_ad(self, platform_ad_id: str) -> bool:
        logger.info("Resuming Meta ad %s", platform_ad_id)

        def _resume() -> bool:
            ad = Ad(platform_ad_id)
            ad.api_update(params={"status": Ad.Status.active})
            return True

        result: bool = await self._run_sync(partial(_resume))  # type: ignore[assignment]
        return result

    async def update_budget(self, platform_ad_id: str, new_budget: float) -> bool:
        """Update the budget on the ad set that owns *platform_ad_id*."""
        logger.info("Updating budget for Meta ad %s to %.2f", platform_ad_id, new_budget)

        def _update_budget() -> bool:
            ad = Ad(platform_ad_id)
            ad_data = ad.api_get(fields=["adset_id"])
            adset_id = ad_data["adset_id"]
            adset = AdSet(adset_id)
            adset.api_update(params={"daily_budget": int(new_budget * 100)})
            return True

        result: bool = await self._run_sync(partial(_update_budget))  # type: ignore[assignment]
        return result

    async def get_metrics(
        self,
        platform_ad_id: str,
        *,
        time_range: tuple[str, str] | None = None,
    ) -> AdMetrics:
        logger.debug(
            "Fetching metrics for Meta ad %s (time_range=%s)",
            platform_ad_id,
            time_range,
        )

        # Full-funnel insight fields requested from Meta API
        _INSIGHT_FIELDS = [
            "impressions",
            "reach",
            "clicks",
            "spend",
            "video_30_sec_watched_actions",
            "video_p25_watched_actions",
            "video_p50_watched_actions",
            "video_p75_watched_actions",
            "video_p100_watched_actions",
            "actions",
            "action_values",
            "cost_per_action_type",
            "outbound_clicks",
        ]

        # When ``time_range`` is provided, ask Meta for that exact window
        # so the daily-report path can fetch yesterday's settled numbers
        # instead of the partial current-day snapshot.
        if time_range is not None:
            since, until = time_range
            params: dict[str, object] = {
                "time_range": {"since": since, "until": until},
            }
        else:
            params = {"date_preset": "today"}

        def _get_metrics() -> dict[str, object]:
            ad = Ad(platform_ad_id)
            insights = ad.get_insights(
                fields=_INSIGHT_FIELDS,
                params=params,
            )
            if not insights:
                return {}
            return dict(insights[0])

        raw: dict[str, object] = await self._run_sync(partial(_get_metrics))  # type: ignore[assignment]
        return self._parse_insights_to_metrics(raw)

    @staticmethod
    def _parse_insights_to_metrics(raw: dict[str, object]) -> AdMetrics:
        """Parse a Meta Insights row into an AdMetrics dataclass."""
        if not raw:
            return AdMetrics(impressions=0, clicks=0, conversions=0, spend=0.0)

        def _action_value(actions: list[dict[str, str]] | None, action_types: list[str]) -> int:
            """Sum values for matching action types."""
            if not actions:
                return 0
            total = 0
            for a in actions:
                if a.get("action_type") in action_types:
                    total += int(float(a.get("value", 0)))
            return total

        def _action_float_value(
            actions: list[dict[str, str]] | None, action_types: list[str]
        ) -> float:
            """Sum float values for matching action types (e.g. purchase_value)."""
            if not actions:
                return 0.0
            total = 0.0
            for a in actions:
                if a.get("action_type") in action_types:
                    total += float(a.get("value", 0))
            return total

        actions = raw.get("actions") or []
        action_values = raw.get("action_values") or []

        # Video views: Meta reports "video_view" in actions for 3-sec views
        video_views_3s = _action_value(actions, ["video_view"])
        # 15-sec and thruplay views are also in actions
        video_views_15s = _action_value(actions, ["video_15_sec_watched_actions"])
        thruplays = _action_value(actions, ["video_thruplay_watched_actions"])

        # If 15s not in actions, try the dedicated fields
        if video_views_15s == 0:
            v15_field = raw.get("video_p50_watched_actions") or []
            video_views_15s = _action_value(v15_field, ["video_view"])

        # Link clicks via outbound_clicks or from actions
        outbound = raw.get("outbound_clicks") or []
        link_clicks = _action_value(outbound, ["outbound_click"])
        if link_clicks == 0:
            link_clicks = _action_value(actions, ["link_click"])

        landing_page_views = _action_value(actions, ["landing_page_view"])
        add_to_carts = _action_value(
            actions, ["offsite_conversion.fb_pixel_add_to_cart", "add_to_cart"]
        )
        purchases = _action_value(
            actions,
            [
                "offsite_conversion.fb_pixel_purchase",
                "purchase",
            ],
        )
        purchase_value = _action_float_value(
            action_values,
            [
                "offsite_conversion.fb_pixel_purchase",
                "purchase",
            ],
        )

        # Lead submissions — Meta scatters them across three action
        # types depending on whether the lead came from an on-site
        # form, an off-site pixel, or an Instant Form. ``leads`` is
        # the dedicated field for ``OUTCOME_LEADS`` reports; we also
        # fold the same count into ``conversions`` below so legacy
        # CTR/CPA aggregates still see lead campaigns as converting.
        leads = _action_value(
            actions,
            [
                "lead",
                "onsite_conversion.lead_grouped",
                "offsite_conversion.fb_pixel_lead",
            ],
        )

        # Post engagements — the ``OUTCOME_ENGAGEMENT`` headline
        # number. Meta already exposes an aggregate ``post_engagement``
        # action (sum of reactions, comments, shares) plus individual
        # breakdowns. Prefer the aggregate when present; fall back to
        # summing individuals so campaigns that only report the
        # breakdowns still get a real number.
        post_engagements = _action_value(actions, ["post_engagement"])
        if post_engagements == 0:
            post_engagements = _action_value(
                actions, ["post_reaction", "comment", "like", "post"]
            )

        # Conversions: purchases + leads. The ``offsite_conversion``
        # catch-all is intentionally additive here — it covers custom
        # pixel events that aren't any of the named types above.
        conversions = purchases + leads + _action_value(
            actions, ["offsite_conversion"]
        )

        return AdMetrics(
            impressions=int(raw.get("impressions", 0)),
            reach=int(raw.get("reach", 0)),
            clicks=int(raw.get("clicks", 0)),
            conversions=conversions,
            spend=float(raw.get("spend", 0)),
            video_views_3s=video_views_3s,
            video_views_15s=video_views_15s,
            thruplays=thruplays,
            link_clicks=link_clicks,
            landing_page_views=landing_page_views,
            add_to_carts=add_to_carts,
            purchases=purchases,
            purchase_value=purchase_value,
            leads=leads,
            post_engagements=post_engagements,
        )

    async def delete_ad(self, platform_ad_id: str) -> bool:
        logger.info("Deleting Meta ad %s", platform_ad_id)

        def _delete() -> bool:
            ad = Ad(platform_ad_id)
            ad.api_delete()
            return True

        result: bool = await self._run_sync(partial(_delete))  # type: ignore[assignment]
        return result

    # ------------------------------------------------------------------
    # Discovery & historical import
    # ------------------------------------------------------------------

    async def list_campaigns(self) -> list[dict[str, object]]:
        """List every campaign in the ad account.

        Used by the Phase D self-serve import flow: the user picks
        which of their existing Meta campaigns to bring into the
        system. Only the fields needed to populate a picker row are
        returned — name, status, daily budget, created timestamp.
        """
        logger.info("Listing campaigns in Meta account %s", self._ad_account_id)

        from facebook_business.adobjects.campaign import Campaign

        def _list() -> list[dict[str, object]]:
            campaigns = self._account.get_campaigns(
                fields=[
                    Campaign.Field.id,
                    Campaign.Field.name,
                    Campaign.Field.status,
                    Campaign.Field.daily_budget,
                    Campaign.Field.created_time,
                    Campaign.Field.objective,
                ],
            )
            results: list[dict[str, object]] = []
            for c in campaigns:
                raw_budget = c.get("daily_budget")
                # Meta returns daily_budget in the account's currency
                # minor units (e.g. cents) as a string. Normalise to
                # a float in major units so the UI doesn't have to
                # care about currency precision.
                daily_budget: float | None = None
                if raw_budget not in (None, ""):
                    try:
                        daily_budget = float(raw_budget) / 100.0
                    except (TypeError, ValueError):
                        daily_budget = None

                # Normalise the raw Meta objective (ODAX or legacy) to
                # the canonical set before it leaves the adapter — every
                # downstream store / dispatch assumes the canonical
                # form. See ``src/adapters/meta_objective.py``.
                raw_objective = c.get("objective") or None
                normalized_objective = normalize_meta_objective(raw_objective)

                results.append(
                    {
                        "meta_campaign_id": str(c["id"]),
                        "name": c.get("name", ""),
                        "status": c.get("status", "UNKNOWN"),
                        "daily_budget": daily_budget,
                        "created_time": c.get("created_time"),
                        "objective": normalized_objective,
                    }
                )
            return results

        campaigns_list: list[dict[str, object]] = await self._run_sync(partial(_list))  # type: ignore[assignment]
        logger.info("Found %d campaigns in Meta account", len(campaigns_list))
        return campaigns_list

    async def get_campaign_objective(self, campaign_id: str) -> str:
        """Fetch the current objective for one Meta campaign.

        A single-resource version of :meth:`list_campaigns` used for
        opportunistic re-sync — when the cron loop needs to refresh a
        campaign's objective without pulling every campaign in the
        account. The returned value is already normalised via
        :func:`normalize_meta_objective`; ``OUTCOME_UNKNOWN`` is
        returned when Meta doesn't populate the field.
        """
        logger.debug("Fetching objective for Meta campaign %s", campaign_id)

        from facebook_business.adobjects.campaign import Campaign

        def _fetch() -> str | None:
            c = Campaign(campaign_id).api_get(fields=[Campaign.Field.objective])
            raw = c.get("objective") or None
            return str(raw) if raw else None

        raw_objective: str | None = await self._run_sync(partial(_fetch))  # type: ignore[assignment]
        return normalize_meta_objective(raw_objective)

    async def list_campaign_ads(self, campaign_id: str) -> list[dict[str, object]]:
        """List all ads in a Meta campaign with their creative details.

        Returns a list of dicts with keys: ad_id, ad_name, adset_id,
        adset_name, status, creative_id, and the ad creative fields
        (headline, body, link_url, cta_type, image_url) where available.

        Meta ships a handful of incompatible creative shapes and we
        need to flatten them into one:

        - **Static link ads** put the copy in
          ``object_story_spec.link_data`` (name, message, link, picture,
          call_to_action.type).
        - **Video ads** put it in ``object_story_spec.video_data``
          (title, message, image_url, call_to_action).
        - **Dynamic Creative / Advantage+ ads** leave ``object_story_spec``
          with only ``page_id`` and stuff every asset variant into
          ``asset_feed_spec`` (titles[], bodies[], call_to_action_types[],
          link_urls[]). We pick the first non-empty option as the
          "canonical" representation for the single-variant genome;
          ``src.services.campaign_import`` seeds every remaining option
          into the gene pool so the generator can still remix them.
        - Anything missed falls through to the creative's top-level
          ``title``/``body``/``thumbnail_url``.

        Without this fallback chain, Dynamic Creative ads (now the
        default for new Advantage+ campaigns) import as genomes with
        only an ``image_url`` and every other slot empty.
        """
        logger.info("Listing ads for Meta campaign %s", campaign_id)

        from facebook_business.adobjects.campaign import Campaign

        def _first_nonempty_text(items: object) -> str:
            """First ``item["text"]`` that is a non-empty string."""
            if not isinstance(items, list):
                return ""
            for item in items:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        return text
            return ""

        def _first_str(items: object, key: str = "") -> str:
            """First non-empty value from a list (optionally indexed by ``key``)."""
            if not isinstance(items, list) or not items:
                return ""
            first = items[0]
            if key:
                if isinstance(first, dict):
                    value = first.get(key)
                    return value if isinstance(value, str) else ""
                return ""
            return first if isinstance(first, str) else ""

        def _list_ads() -> list[dict[str, object]]:
            campaign = Campaign(campaign_id)
            ads = campaign.get_ads(
                fields=[
                    "id",
                    "name",
                    "status",
                    "adset_id",
                    # ``object_type`` is Meta's own image/video/carousel
                    # discriminator — one authoritative enum per ad
                    # (VIDEO / PHOTO / SHARE / MULTI_SHARE / …). Used
                    # below to populate each ad dict's ``media_type`` so
                    # the reporting layer can hide video-only metrics
                    # (hook rate, hold rate, 3s/15s views) on image ads.
                    "creative{id,name,title,body,object_story_spec,"
                    "asset_feed_spec,thumbnail_url,object_type}",
                ],
            )
            results: list[dict[str, object]] = []
            for ad in ads:
                creative = ad.get("creative", {}) or {}
                story_spec = creative.get("object_story_spec", {}) or {}
                link_data = story_spec.get("link_data", {}) or {}
                video_data = story_spec.get("video_data", {}) or {}
                feed = creative.get("asset_feed_spec", {}) or {}

                headline = (
                    link_data.get("name")
                    or video_data.get("title")
                    or _first_nonempty_text(feed.get("titles"))
                    or creative.get("title", "")
                    or ""
                )
                body = (
                    link_data.get("message")
                    or video_data.get("message")
                    or _first_nonempty_text(feed.get("bodies"))
                    or creative.get("body", "")
                    or ""
                )
                link_url = (
                    link_data.get("link")
                    or video_data.get("call_to_action", {}).get("value", {}).get("link", "")
                    or _first_str(feed.get("link_urls"), "website_url")
                    or ""
                )
                cta_type = (
                    link_data.get("call_to_action", {}).get("type")
                    or video_data.get("call_to_action", {}).get("type")
                    or _first_str(feed.get("call_to_action_types"))
                    or ""
                )
                image_url = (
                    link_data.get("picture")
                    or video_data.get("image_url")
                    or creative.get("thumbnail_url", "")
                    or ""
                )

                results.append(
                    {
                        "ad_id": str(ad["id"]),
                        "ad_name": ad.get("name", ""),
                        "status": ad.get("status", "UNKNOWN"),
                        "adset_id": str(ad.get("adset_id", "")),
                        "creative_id": str(creative.get("id", "")),
                        "creative_name": creative.get("name", ""),
                        "headline": headline,
                        "body": body,
                        "link_url": link_url,
                        "cta_type": cta_type,
                        "image_url": image_url,
                        "media_type": _map_media_type(
                            creative.get("object_type")
                        ),
                        # Full asset-feed variants, for the import
                        # service to seed every option into the gene
                        # pool. Empty for non-Dynamic-Creative ads.
                        "asset_feed_titles": [
                            t.get("text", "")
                            for t in (feed.get("titles") or [])
                            if isinstance(t, dict) and t.get("text")
                        ],
                        "asset_feed_bodies": [
                            b.get("text", "")
                            for b in (feed.get("bodies") or [])
                            if isinstance(b, dict) and b.get("text")
                        ],
                        "asset_feed_cta_types": [
                            c for c in (feed.get("call_to_action_types") or []) if isinstance(c, str) and c
                        ],
                    }
                )
            return results

        ads_list: list[dict[str, object]] = await self._run_sync(partial(_list_ads))  # type: ignore[assignment]
        logger.info("Found %d ads in Meta campaign %s", len(ads_list), campaign_id)
        return ads_list

    async def get_historical_metrics(
        self,
        platform_ad_id: str,
        date_preset: str = "last_30d",
        time_increment: int = 1,
    ) -> list[dict[str, object]]:
        """Fetch daily full-funnel historical metrics for an ad.

        Args:
            platform_ad_id: The Meta ad ID.
            date_preset: Meta date preset — ``last_7d``, ``last_30d``, etc.
            time_increment: Day granularity (1 = daily breakdown).

        Returns:
            List of daily metric dicts with full-funnel fields.
        """
        logger.info("Fetching historical metrics (%s) for ad %s", date_preset, platform_ad_id)

        _INSIGHT_FIELDS = [
            "impressions",
            "reach",
            "clicks",
            "spend",
            "actions",
            "action_values",
            "outbound_clicks",
            "video_30_sec_watched_actions",
            "video_p50_watched_actions",
        ]

        def _fetch() -> list[dict[str, object]]:
            ad = Ad(platform_ad_id)
            insights = ad.get_insights(
                fields=_INSIGHT_FIELDS,
                params={
                    "date_preset": date_preset,
                    "time_increment": time_increment,
                },
            )
            rows: list[dict[str, object]] = []
            for row in insights:
                metrics = MetaAdapter._parse_insights_to_metrics(dict(row))
                rows.append(
                    {
                        "date_start": row.get("date_start", ""),
                        "date_stop": row.get("date_stop", ""),
                        "impressions": metrics.impressions,
                        "reach": metrics.reach,
                        "clicks": metrics.clicks,
                        "conversions": metrics.conversions,
                        "spend": metrics.spend,
                        "video_views_3s": metrics.video_views_3s,
                        "video_views_15s": metrics.video_views_15s,
                        "thruplays": metrics.thruplays,
                        "link_clicks": metrics.link_clicks,
                        "landing_page_views": metrics.landing_page_views,
                        "add_to_carts": metrics.add_to_carts,
                        "purchases": metrics.purchases,
                        "purchase_value": metrics.purchase_value,
                    }
                )
            return rows

        result: list[dict[str, object]] = await self._run_sync(partial(_fetch))  # type: ignore[assignment]
        logger.info("Got %d daily rows for ad %s", len(result), platform_ad_id)
        return result

    # ------------------------------------------------------------------
    # Targeting helper
    # ------------------------------------------------------------------

    def _build_targeting(
        self,
        genome: dict[str, str],
        audience_meta: dict | None = None,
    ) -> dict[str, object]:
        """Build Meta targeting spec from genome audience slot.

        If ``audience_meta`` contains a ``meta_audience_id`` key (from the
        gene pool metadata), it is used as the custom audience. Otherwise
        broad targeting is used.
        """
        targeting: dict[str, object] = {
            "geo_locations": {"countries": ["US"]},
            "age_min": 18,
            "age_max": 65,
        }

        # Use real Meta audience ID from gene pool metadata if available
        if audience_meta and audience_meta.get("meta_audience_id"):
            targeting["custom_audiences"] = [{"id": audience_meta["meta_audience_id"]}]

        return targeting

    # ------------------------------------------------------------------
    # Media library
    # ------------------------------------------------------------------

    async def list_media_library(
        self,
        asset_type: str = "all",
    ) -> list[MediaAsset]:
        """List images and/or videos from the Meta ad account's library.

        Args:
            asset_type: ``"image"``, ``"video"``, or ``"all"``.

        Returns:
            List of ``MediaAsset`` objects with platform IDs and metadata.
        """
        assets: list[MediaAsset] = []

        if asset_type in ("image", "all"):

            def _list_images() -> list[MediaAsset]:
                images = self._account.get_ad_images(
                    fields=[
                        AdImage.Field.hash,
                        AdImage.Field.name,
                        AdImage.Field.url,
                        AdImage.Field.url_128,
                        AdImage.Field.permalink_url,
                        AdImage.Field.width,
                        AdImage.Field.height,
                        AdImage.Field.created_time,
                        AdImage.Field.status,
                    ],
                )
                result: list[MediaAsset] = []
                for img in images:
                    result.append(
                        MediaAsset(
                            asset_type="image",
                            platform_id=str(img.get(AdImage.Field.hash, "")),
                            name=str(img.get(AdImage.Field.name, "Untitled")),
                            thumbnail_url=str(img.get(AdImage.Field.url_128, "")),
                            source_url=str(img.get(AdImage.Field.url, "")),
                            width=int(img.get(AdImage.Field.width, 0)),
                            height=int(img.get(AdImage.Field.height, 0)),
                            metadata={
                                "permalink_url": str(img.get(AdImage.Field.permalink_url, "")),
                                "created_time": str(img.get(AdImage.Field.created_time, "")),
                                "status": str(img.get(AdImage.Field.status, "")),
                            },
                        )
                    )
                return result

            img_assets: list[MediaAsset] = await self._run_sync(partial(_list_images))  # type: ignore[assignment]
            assets.extend(img_assets)
            logger.info("Found %d images in media library", len(img_assets))

        if asset_type in ("video", "all"):

            def _list_videos() -> list[MediaAsset]:
                videos = self._account.get_ad_videos(
                    fields=[
                        AdVideo.Field.id,
                        AdVideo.Field.title,
                        AdVideo.Field.description,
                        AdVideo.Field.picture,
                        AdVideo.Field.source,
                        AdVideo.Field.length,
                        AdVideo.Field.created_time,
                    ],
                )
                result: list[MediaAsset] = []
                for vid in videos:
                    result.append(
                        MediaAsset(
                            asset_type="video",
                            platform_id=str(vid.get(AdVideo.Field.id, "")),
                            name=str(vid.get(AdVideo.Field.title, "Untitled")),
                            thumbnail_url=str(vid.get(AdVideo.Field.picture, "")),
                            source_url=str(vid.get(AdVideo.Field.source, "")),
                            duration_secs=float(vid.get(AdVideo.Field.length, 0)),
                            metadata={
                                "description": str(vid.get(AdVideo.Field.description, "")),
                                "created_time": str(vid.get(AdVideo.Field.created_time, "")),
                            },
                        )
                    )
                return result

            vid_assets: list[MediaAsset] = await self._run_sync(partial(_list_videos))  # type: ignore[assignment]
            assets.extend(vid_assets)
            logger.info("Found %d videos in media library", len(vid_assets))

        return assets

    def _build_video_creative_params(
        self,
        variant_code: str,
        genome: dict[str, str],
        video_id: str,
        thumbnail_hash: str | None = None,
    ) -> dict[str, object]:
        """Build Meta ad creative params for a video ad."""
        headline = genome.get("headline", "")
        subhead = genome.get("subhead", "")
        cta_text = genome.get("cta_text", "")

        cta_map: dict[str, str] = {
            "Claim my discount": "GET_OFFER",
            "Shop now": "SHOP_NOW",
            "Learn more": "LEARN_MORE",
            "Sign up free": "SIGN_UP",
            "Start my trial": "SIGN_UP",
            "Get started": "LEARN_MORE",
        }
        cta_type = cta_map.get(cta_text, "LEARN_MORE")

        video_data: dict[str, object] = {
            "video_id": video_id,
            "title": headline,
            "message": subhead,
            "call_to_action": {
                "type": cta_type,
                "value": {"link": self._landing_page_url},
            },
        }
        if thumbnail_hash:
            video_data["image_hash"] = thumbnail_hash

        return {
            "name": f"AdAgent {variant_code}",
            "object_story_spec": {
                "page_id": self._page_id,
                "video_data": video_data,
            },
        }
