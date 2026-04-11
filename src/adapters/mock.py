"""Mock adapter for testing.

Implements ``BaseAdapter`` with in-memory storage, deterministic or
random metric generation, and full call recording for test assertions.
Supports configurable failure modes so tests can exercise error paths
without touching real APIs.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from src.adapters.base import AdMetrics, BaseAdapter
from src.exceptions import PlatformAPIError

logger = logging.getLogger(__name__)


class FailureMode(Enum):
    """Configurable failure scenarios for the mock adapter."""

    NONE = "none"
    CREATE_FAILS = "create_fails"
    PAUSE_FAILS = "pause_fails"
    RESUME_FAILS = "resume_fails"
    UPDATE_BUDGET_FAILS = "update_budget_fails"
    GET_METRICS_FAILS = "get_metrics_fails"
    DELETE_FAILS = "delete_fails"
    ALL_FAIL = "all_fail"
    INTERMITTENT = "intermittent"  # fails every other call


AdStatus = Literal["active", "paused", "deleted"]


@dataclass
class MockAdRecord:
    """In-memory representation of a mock ad."""

    platform_ad_id: str
    campaign_id: str
    variant_code: str
    genome: dict[str, str]
    daily_budget: float
    status: AdStatus = "active"


@dataclass
class CallRecord:
    """Record of a single adapter method invocation."""

    method: str
    args: dict[str, object]


class MockAdapter(BaseAdapter):
    """In-memory mock adapter for unit and integration tests.

    Usage::

        adapter = MockAdapter(seed=42)  # reproducible metrics
        ad_id = await adapter.create_ad("camp-1", "V1", genome, 50.0)
        metrics = await adapter.get_metrics(ad_id)
        assert adapter.call_count("create_ad") == 1
    """

    def __init__(
        self,
        seed: int | None = None,
        failure_mode: FailureMode = FailureMode.NONE,
    ) -> None:
        self._ads: dict[str, MockAdRecord] = {}
        self._calls: list[CallRecord] = []
        self._failure_mode = failure_mode
        self._call_counter: int = 0
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Inspection helpers for tests
    # ------------------------------------------------------------------

    @property
    def ads(self) -> dict[str, MockAdRecord]:
        """All ads currently stored in the mock."""
        return dict(self._ads)

    @property
    def calls(self) -> list[CallRecord]:
        """Ordered list of every call made to the adapter."""
        return list(self._calls)

    def call_count(self, method: str) -> int:
        """Return how many times *method* was invoked."""
        return sum(1 for c in self._calls if c.method == method)

    def calls_for(self, method: str) -> list[CallRecord]:
        """Return all call records for *method*."""
        return [c for c in self._calls if c.method == method]

    def reset(self) -> None:
        """Clear all state (ads and call history)."""
        self._ads.clear()
        self._calls.clear()
        self._call_counter = 0

    # ------------------------------------------------------------------
    # Failure simulation
    # ------------------------------------------------------------------

    def set_failure_mode(self, mode: FailureMode) -> None:
        """Change the failure mode at runtime (useful mid-test)."""
        self._failure_mode = mode

    def _should_fail(self, method: str) -> bool:
        """Determine whether the current call should raise an error."""
        self._call_counter += 1
        if self._failure_mode == FailureMode.NONE:
            return False
        if self._failure_mode == FailureMode.ALL_FAIL:
            return True
        if self._failure_mode == FailureMode.INTERMITTENT:
            return self._call_counter % 2 == 0
        # Check method-specific failure modes
        mode_map: dict[FailureMode, str] = {
            FailureMode.CREATE_FAILS: "create_ad",
            FailureMode.PAUSE_FAILS: "pause_ad",
            FailureMode.RESUME_FAILS: "resume_ad",
            FailureMode.UPDATE_BUDGET_FAILS: "update_budget",
            FailureMode.GET_METRICS_FAILS: "get_metrics",
            FailureMode.DELETE_FAILS: "delete_ad",
        }
        return mode_map.get(self._failure_mode) == method

    def _maybe_fail(self, method: str) -> None:
        """Raise ``PlatformAPIError`` if the current call should fail."""
        if self._should_fail(method):
            raise PlatformAPIError(
                platform="mock",
                message=f"Simulated failure in {method}",
                response_body=f'{{"error": "mock_{method}_failure"}}',
            )

    def _record(self, method: str, **kwargs: object) -> None:
        self._calls.append(CallRecord(method=method, args=kwargs))

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
        self._record(
            "create_ad",
            campaign_id=campaign_id,
            variant_code=variant_code,
            genome=genome,
            daily_budget=daily_budget,
            media_info=media_info,
        )
        self._maybe_fail("create_ad")

        platform_ad_id = f"mock-ad-{uuid.uuid4().hex[:12]}"
        self._ads[platform_ad_id] = MockAdRecord(
            platform_ad_id=platform_ad_id,
            campaign_id=campaign_id,
            variant_code=variant_code,
            genome=dict(genome),
            daily_budget=daily_budget,
            status="active",
        )
        logger.debug("MockAdapter created ad %s for %s", platform_ad_id, variant_code)
        return platform_ad_id

    def _ensure_ad(self, platform_ad_id: str) -> MockAdRecord:
        """Return the ad record, auto-registering unknown IDs.

        In development the MockAdapter is recreated on each CLI invocation,
        so ads deployed in a previous run won't be in memory. This method
        lazily creates a stub record so that get_metrics, pause, resume, and
        update_budget work across process restarts.
        """
        ad = self._ads.get(platform_ad_id)
        if ad is None:
            ad = MockAdRecord(
                platform_ad_id=platform_ad_id,
                campaign_id="unknown",
                variant_code="unknown",
                genome={},
                daily_budget=50.0,
                status="active",
            )
            self._ads[platform_ad_id] = ad
            logger.debug("MockAdapter auto-registered ad %s", platform_ad_id)
        return ad

    async def pause_ad(self, platform_ad_id: str) -> bool:
        self._record("pause_ad", platform_ad_id=platform_ad_id)
        self._maybe_fail("pause_ad")

        ad = self._ensure_ad(platform_ad_id)
        ad.status = "paused"
        return True

    async def resume_ad(self, platform_ad_id: str) -> bool:
        self._record("resume_ad", platform_ad_id=platform_ad_id)
        self._maybe_fail("resume_ad")

        ad = self._ensure_ad(platform_ad_id)
        ad.status = "active"
        return True

    async def update_budget(self, platform_ad_id: str, new_budget: float) -> bool:
        self._record(
            "update_budget",
            platform_ad_id=platform_ad_id,
            new_budget=new_budget,
        )
        self._maybe_fail("update_budget")

        ad = self._ensure_ad(platform_ad_id)
        ad.daily_budget = new_budget
        return True

    async def get_metrics(
        self,
        platform_ad_id: str,
        *,
        time_range: tuple[str, str] | None = None,
    ) -> AdMetrics:
        self._record(
            "get_metrics",
            platform_ad_id=platform_ad_id,
            time_range=time_range,
        )
        self._maybe_fail("get_metrics")

        ad = self._ensure_ad(platform_ad_id)

        # Generate realistic random metrics
        impressions = self._rng.randint(100, 10_000)
        # CTR between 0.5% and 5%
        ctr = self._rng.uniform(0.005, 0.05)
        clicks = max(1, int(impressions * ctr))
        # Conversion rate between 1% and 10% of clicks
        conversion_rate = self._rng.uniform(0.01, 0.10)
        conversions = max(0, int(clicks * conversion_rate))
        # CPC between $0.20 and $3.00
        cpc = self._rng.uniform(0.20, 3.00)
        spend = round(clicks * cpc, 2)
        # Cap spend at daily budget
        spend = min(spend, ad.daily_budget)

        return AdMetrics(
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            spend=spend,
        )

    async def delete_ad(self, platform_ad_id: str) -> bool:
        self._record("delete_ad", platform_ad_id=platform_ad_id)
        self._maybe_fail("delete_ad")

        ad = self._ensure_ad(platform_ad_id)
        ad.status = "deleted"
        del self._ads[platform_ad_id]
        return True
