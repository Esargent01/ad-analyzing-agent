"""Google Ads API adapter.

Uses the ``google-ads-python`` SDK for ad management and metrics retrieval.
All external calls go through ``asyncio.to_thread`` because the Google Ads
client is synchronous.  Errors are caught and re-raised as
``PlatformAPIError`` with the full gRPC error detail.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from src.adapters.base import AdMetrics, BaseAdapter
from src.exceptions import PlatformAPIError

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 2.0


class GoogleAdsAdapter(BaseAdapter):
    """Google Ads API adapter using responsive search ads.

    The adapter maps creative genome slots to Google responsive ad
    components: headlines, descriptions, and display paths.
    """

    def __init__(
        self,
        developer_token: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        customer_id: str,
    ) -> None:
        self._customer_id = customer_id.replace("-", "")
        self._client: GoogleAdsClient = GoogleAdsClient.load_from_dict(
            {
                "developer_token": developer_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "login_customer_id": self._customer_id,
            }
        )
        logger.info("GoogleAdsAdapter initialised for customer %s", self._customer_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_sync(self, fn: partial[object]) -> object:
        """Run a synchronous SDK call in a thread with retry + backoff."""
        last_error: GoogleAdsException | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await asyncio.to_thread(fn)
            except GoogleAdsException as exc:
                last_error = exc
                # Check for rate limit errors (RESOURCE_EXHAUSTED)
                is_rate_limit = any(
                    err.error_code.quota_error
                    for err in exc.failure.errors
                    if hasattr(err.error_code, "quota_error")
                )
                if is_rate_limit:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Google Ads rate limit hit (attempt %d/%d), backing off %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise self._wrap_error(exc) from exc

        assert last_error is not None
        raise self._wrap_error(last_error) from last_error

    @staticmethod
    def _wrap_error(exc: GoogleAdsException) -> PlatformAPIError:
        error_messages = [str(err.message) for err in exc.failure.errors]
        return PlatformAPIError(
            platform="google_ads",
            message=f"Google Ads API error: {'; '.join(error_messages)}",
            response_body=str(exc.failure),
        )

    def _resource_name(self, resource_type: str, resource_id: str) -> str:
        """Build a Google Ads resource name."""
        return f"customers/{self._customer_id}/{resource_type}/{resource_id}"

    def _build_responsive_ad_operation(
        self,
        variant_code: str,
        genome: dict[str, str],
    ) -> dict[str, list[str]]:
        """Map genome slots to responsive search ad components.

        Returns a dict with ``headlines`` and ``descriptions`` lists.
        """
        headline = genome.get("headline", "")
        subhead = genome.get("subhead", "")
        cta_text = genome.get("cta_text", "Learn more")

        # Google responsive search ads support up to 15 headlines / 4 descriptions.
        # We provide 3 headlines and 2 descriptions from the genome.
        headlines = [
            headline[:30],  # Google headline max 30 chars
            subhead[:30],
            cta_text[:30],
        ]
        descriptions = [
            f"{headline} {subhead}"[:90],  # description max 90 chars
            f"{cta_text} - {variant_code}"[:90],
        ]
        return {"headlines": headlines, "descriptions": descriptions}

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
        """Create a responsive search ad in *campaign_id*.

        Steps:
        1. Create an ad group with budget settings.
        2. Create a responsive search ad in that ad group.
        """
        logger.info("Creating Google ad for %s in campaign %s", variant_code, campaign_id)
        ad_parts = self._build_responsive_ad_operation(variant_code, genome)

        def _create() -> str:
            # --- Ad Group ---
            ag_service = self._client.get_service("AdGroupService")
            ag_operation = self._client.get_type("AdGroupOperation")
            ad_group = ag_operation.create
            ad_group.name = f"AdAgent {variant_code}"
            ad_group.campaign = self._resource_name("campaigns", campaign_id)
            ad_group.status = self._client.enums.AdGroupStatusEnum.ENABLED
            ad_group.cpc_bid_micros = int(daily_budget * 1_000_000 / 10)  # rough heuristic

            ag_response = ag_service.mutate_ad_groups(
                customer_id=self._customer_id,
                operations=[ag_operation],
            )
            ad_group_resource = ag_response.results[0].resource_name

            # --- Responsive Search Ad ---
            ad_service = self._client.get_service("AdGroupAdService")
            ad_operation = self._client.get_type("AdGroupAdOperation")
            ad_group_ad = ad_operation.create
            ad_group_ad.ad_group = ad_group_resource
            ad_group_ad.status = self._client.enums.AdGroupAdStatusEnum.ENABLED

            rsa = ad_group_ad.ad.responsive_search_ad
            for text in ad_parts["headlines"]:
                headline_asset = self._client.get_type("AdTextAsset")
                headline_asset.text = text
                rsa.headlines.append(headline_asset)

            for text in ad_parts["descriptions"]:
                desc_asset = self._client.get_type("AdTextAsset")
                desc_asset.text = text
                rsa.descriptions.append(desc_asset)

            ad_group_ad.ad.final_urls.append("https://example.com")
            ad_group_ad.ad.name = f"AdAgent RSA {variant_code}"

            ad_response = ad_service.mutate_ad_group_ads(
                customer_id=self._customer_id,
                operations=[ad_operation],
            )
            return ad_response.results[0].resource_name

        resource_name: str = await self._run_sync(partial(_create))  # type: ignore[assignment]
        logger.info("Created Google ad %s", resource_name)
        return resource_name

    async def pause_ad(self, platform_ad_id: str) -> bool:
        logger.info("Pausing Google ad %s", platform_ad_id)

        def _pause() -> bool:
            service = self._client.get_service("AdGroupAdService")
            operation = self._client.get_type("AdGroupAdOperation")
            operation.update.resource_name = platform_ad_id
            operation.update.status = self._client.enums.AdGroupAdStatusEnum.PAUSED
            self._client.copy_from(
                operation.update_mask,
                self._client.get_type("FieldMask")(paths=["status"]),
            )
            service.mutate_ad_group_ads(
                customer_id=self._customer_id,
                operations=[operation],
            )
            return True

        result: bool = await self._run_sync(partial(_pause))  # type: ignore[assignment]
        return result

    async def resume_ad(self, platform_ad_id: str) -> bool:
        logger.info("Resuming Google ad %s", platform_ad_id)

        def _resume() -> bool:
            service = self._client.get_service("AdGroupAdService")
            operation = self._client.get_type("AdGroupAdOperation")
            operation.update.resource_name = platform_ad_id
            operation.update.status = self._client.enums.AdGroupAdStatusEnum.ENABLED
            self._client.copy_from(
                operation.update_mask,
                self._client.get_type("FieldMask")(paths=["status"]),
            )
            service.mutate_ad_group_ads(
                customer_id=self._customer_id,
                operations=[operation],
            )
            return True

        result: bool = await self._run_sync(partial(_resume))  # type: ignore[assignment]
        return result

    async def update_budget(self, platform_ad_id: str, new_budget: float) -> bool:
        """Update the CPC bid on the ad group owning *platform_ad_id*.

        Google Ads doesn't set budgets on individual ads; we adjust the
        ad group's CPC bid as a proxy.
        """
        logger.info("Updating budget for Google ad %s to %.2f", platform_ad_id, new_budget)

        def _update() -> bool:
            # Extract ad group resource name from the ad resource name
            # Format: customers/{id}/adGroupAds/{ag_id}~{ad_id}
            ga_service = self._client.get_service("GoogleAdsService")
            query = (
                f"SELECT ad_group.resource_name "
                f"FROM ad_group_ad "
                f"WHERE ad_group_ad.resource_name = '{platform_ad_id}'"
            )
            response = ga_service.search(customer_id=self._customer_id, query=query)
            rows = list(response)
            if not rows:
                raise PlatformAPIError(
                    platform="google_ads",
                    message=f"Ad not found: {platform_ad_id}",
                )
            ad_group_resource = rows[0].ad_group.resource_name

            ag_service = self._client.get_service("AdGroupService")
            operation = self._client.get_type("AdGroupOperation")
            operation.update.resource_name = ad_group_resource
            operation.update.cpc_bid_micros = int(new_budget * 1_000_000 / 10)
            self._client.copy_from(
                operation.update_mask,
                self._client.get_type("FieldMask")(paths=["cpc_bid_micros"]),
            )
            ag_service.mutate_ad_groups(
                customer_id=self._customer_id,
                operations=[operation],
            )
            return True

        result: bool = await self._run_sync(partial(_update))  # type: ignore[assignment]
        return result

    async def get_metrics(self, platform_ad_id: str) -> AdMetrics:
        logger.debug("Fetching metrics for Google ad %s", platform_ad_id)

        def _get_metrics() -> dict[str, int | float]:
            ga_service = self._client.get_service("GoogleAdsService")
            query = (
                "SELECT "
                "  metrics.impressions, "
                "  metrics.clicks, "
                "  metrics.conversions, "
                "  metrics.cost_micros "
                "FROM ad_group_ad "
                f"WHERE ad_group_ad.resource_name = '{platform_ad_id}' "
                "AND segments.date DURING TODAY"
            )
            response = ga_service.search(customer_id=self._customer_id, query=query)
            rows = list(response)
            if not rows:
                return {"impressions": 0, "clicks": 0, "conversions": 0, "spend": 0.0}
            row = rows[0]
            return {
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": int(row.metrics.conversions),
                "spend": row.metrics.cost_micros / 1_000_000,
            }

        raw: dict[str, int | float] = await self._run_sync(partial(_get_metrics))  # type: ignore[assignment]
        return AdMetrics(
            impressions=int(raw["impressions"]),
            clicks=int(raw["clicks"]),
            conversions=int(raw["conversions"]),
            spend=float(raw["spend"]),
        )

    async def delete_ad(self, platform_ad_id: str) -> bool:
        logger.info("Deleting Google ad %s", platform_ad_id)

        def _delete() -> bool:
            service = self._client.get_service("AdGroupAdService")
            operation = self._client.get_type("AdGroupAdOperation")
            operation.remove = platform_ad_id
            service.mutate_ad_group_ads(
                customer_id=self._customer_id,
                operations=[operation],
            )
            return True

        result: bool = await self._run_sync(partial(_delete))  # type: ignore[assignment]
        return result
