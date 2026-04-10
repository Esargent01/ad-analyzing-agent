"""Integration tests for the Orchestrator with mocked externals.

The orchestrator depends heavily on the database (Postgres + TimescaleDB),
so these tests mock the session factory and verify the orchestration logic,
phase progression, and report generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.mock import MockAdapter
from src.services.orchestrator import CycleAction, CycleReport, Orchestrator, _VariantData


def _make_settings(**overrides: object) -> SimpleNamespace:
    """Create a mock Settings object with sensible defaults."""
    defaults = {
        "min_impressions": 1000,
        "confidence_threshold": 0.95,
        "max_concurrent_variants": 10,
        "anthropic_api_key": "sk-test",
        "anthropic_model": "claude-sonnet-4-20250514",
        "log_level": "DEBUG",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_mock_session_factory() -> tuple[async_sessionmaker, AsyncMock]:
    """Create a mock async_sessionmaker that returns a mock AsyncSession.

    Returns:
        Tuple of (session_factory, mock_session) for test assertions.
    """
    mock_session = AsyncMock(spec=AsyncSession)

    # Make execute return mock result sets
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (1,)  # next_cycle_number returns 1
    mock_result.fetchall.return_value = []  # no deployments/variants by default
    mock_session.execute.return_value = mock_result
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    # async context manager
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(spec=async_sessionmaker)
    factory.return_value = mock_session

    return factory, mock_session


class TestOrchestrator:
    """Integration tests for the Orchestrator.run_cycle() method."""

    async def test_full_cycle_returns_cycle_report(self) -> None:
        """run_cycle should complete and return a CycleReport."""
        adapter = MockAdapter(seed=42)
        factory, mock_session = _make_mock_session_factory()
        settings = _make_settings()

        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=factory,
            settings=settings,
        )

        campaign_id = uuid.uuid4()
        report = await orchestrator.run_cycle(campaign_id)

        assert isinstance(report, CycleReport)
        assert report.campaign_id == campaign_id
        assert report.cycle_number == 1

    async def test_cycle_report_has_summary_text(self) -> None:
        """The report phase should generate a summary_text."""
        adapter = MockAdapter(seed=42)
        factory, mock_session = _make_mock_session_factory()
        settings = _make_settings()

        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=factory,
            settings=settings,
        )

        campaign_id = uuid.uuid4()
        report = await orchestrator.run_cycle(campaign_id)

        # Summary should contain the campaign ID and cycle number
        assert report.summary_text
        assert str(campaign_id) in report.summary_text

    async def test_monitor_phase_with_no_deployments(self) -> None:
        """Monitor phase with no active deployments should collect 0 snapshots."""
        adapter = MockAdapter(seed=42)
        factory, mock_session = _make_mock_session_factory()
        settings = _make_settings()

        # The DB query for active deployments returns empty
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=factory,
            settings=settings,
        )

        report = await orchestrator.run_cycle(uuid.uuid4())
        assert report.snapshots_collected == 0

    async def test_phase_reached_progresses(self) -> None:
        """The phase_reached field should advance through the phases."""
        adapter = MockAdapter(seed=42)
        factory, mock_session = _make_mock_session_factory()
        settings = _make_settings()

        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=factory,
            settings=settings,
        )

        report = await orchestrator.run_cycle(uuid.uuid4())

        # Should reach the final phase if no errors
        assert report.phase_reached == "report"

    async def test_cycle_report_fields_are_populated(self) -> None:
        """Verify all expected CycleReport fields have appropriate values."""
        adapter = MockAdapter(seed=42)
        factory, mock_session = _make_mock_session_factory()
        settings = _make_settings()

        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=factory,
            settings=settings,
        )

        report = await orchestrator.run_cycle(uuid.uuid4())

        assert isinstance(report.cycle_id, uuid.UUID)
        assert isinstance(report.campaign_id, uuid.UUID)
        assert report.cycle_number >= 1
        assert isinstance(report.actions, list)
        assert isinstance(report.errors, dict)
        assert isinstance(report.snapshots_collected, int)
        assert isinstance(report.variants_launched, int)
        assert isinstance(report.variants_paused, int)
        assert isinstance(report.variants_promoted, int)


class TestCycleReport:
    """Tests for the CycleReport dataclass defaults."""

    def test_default_values(self) -> None:
        """CycleReport defaults should be sensible."""
        report = CycleReport(
            cycle_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            cycle_number=1,
        )
        assert report.phase_reached == "monitor"
        assert report.snapshots_collected == 0
        assert report.variants_launched == 0
        assert report.variants_paused == 0
        assert report.variants_promoted == 0
        assert report.actions == []
        assert report.errors == {}
        assert report.summary_text == ""


class TestCycleAction:
    """Tests for the CycleAction dataclass."""

    def test_creation(self) -> None:
        action = CycleAction(
            variant_id=uuid.uuid4(),
            action="pause",
            details={"reason": "underperformer", "p_value": 0.001},
        )
        assert action.action == "pause"
        assert action.details["reason"] == "underperformer"

    def test_null_variant_id(self) -> None:
        action = CycleAction(
            variant_id=None,
            action="system_check",
            details={"status": "ok"},
        )
        assert action.variant_id is None


class TestVariantData:
    """Tests for the _VariantData internal struct."""

    def test_creation(self) -> None:
        vd = _VariantData(
            variant_id=uuid.uuid4(),
            variant_code="V1",
            status="active",
            genome={"headline": "test"},
            impressions=5000,
            clicks=150,
            conversions=15,
            spend=75.0,
        )
        assert vd.variant_code == "V1"
        assert vd.impressions == 5000

    def test_frozen(self) -> None:
        vd = _VariantData(
            variant_id=uuid.uuid4(),
            variant_code="V1",
            status="active",
            genome={},
            impressions=0,
            clicks=0,
            conversions=0,
            spend=0.0,
        )
        with pytest.raises(AttributeError):
            vd.impressions = 999  # type: ignore[misc]
