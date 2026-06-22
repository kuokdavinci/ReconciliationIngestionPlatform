"""Tests for DailyReporter — format only, no duplicate computation."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest



def _make_mock_result(status: str = "MATCHED", partner: str = "MOMO") -> SimpleNamespace:
    """Create a mock reconciliation result."""
    from src.core.enums import ReconciliationStatus

    r = SimpleNamespace()
    r.partner = partner
    r.date = "2024-07-07"
    r.partner_amount = Decimal("100000")
    r.internal_amount = Decimal("100000")
    r.reconciliation_status = ReconciliationStatus(status)
    return r


class MockLLMProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response: str = "", should_fail: bool = False):
        self._response = response
        self._should_fail = should_fail

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        if self._should_fail:
            raise RuntimeError("LLM call failed")
        return self._response


class TestDailyReporterInit:
    """Test DailyReporter initialization."""

    def test_initializes_with_defaults(self) -> None:
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_provider = MockLLMProvider()

        reporter = DailyReporter(mock_collection, mock_provider)

        assert reporter.collection is mock_collection
        assert reporter.llm_provider is mock_provider
        assert reporter.config is not None

    def test_initializes_with_custom_config(self) -> None:
        from src.analysis.config import AnalysisConfig
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_provider = MockLLMProvider()
        config = AnalysisConfig(alert_mismatch_rate_threshold=10.0)

        reporter = DailyReporter(mock_collection, mock_provider, config)

        assert reporter.config.alert_mismatch_rate_threshold == 10.0


class TestDailyReporterGenerateReport:
    """Test DailyReporter.generate_report()."""

    @pytest.mark.asyncio
    async def test_returns_empty_report_when_no_partners(self) -> None:
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=[])

        reporter = DailyReporter(mock_collection, MockLLMProvider())
        report = await reporter.generate_report("2024-07-07")

        assert report["date"] == "2024-07-07"
        assert report["partners"] == []
        assert report["global_stats"]["total_mismatch_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_generates_report_for_partners(self) -> None:
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=["MOMO"])

        mock_summary = {
            "partner": "MOMO",
            "date": "2024-07-07",
            "summary_metrics": {
                "total_transactions": 100,
                "matched": 95,
                "mismatch_rate": 5.0,
                "total_amount_mismatch": 500000,
                "by_status": {"MATCHED": 95, "AMOUNT_MISMATCH": 5},
            },
            "grouped_stats": [],
            "key_findings": ["Test finding"],
            "generated_at": "2024-07-07",
            "llm_status": "success",
        }

        with patch("src.analysis.insights.get_summary", new_callable=AsyncMock) as mock_get_summary:
            mock_get_summary.return_value = mock_summary

            reporter = DailyReporter(mock_collection, MockLLMProvider())
            report = await reporter.generate_report("2024-07-07")

        assert report["date"] == "2024-07-07"
        assert len(report["partners"]) == 1
        assert report["partners"][0]["partner"] == "MOMO"
        assert report["partners"][0]["summary_metrics"]["total_transactions"] == 100
        assert report["global_stats"]["total_volume"] == 100

    @pytest.mark.asyncio
    async def test_skips_failed_partners(self) -> None:
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=["MOMO", "VIETTEL"])

        mock_summary = {
            "partner": "VIETTEL",
            "date": "2024-07-07",
            "summary_metrics": {
                "total_transactions": 50,
                "matched": 50,
                "mismatch_rate": 0.0,
                "total_amount_mismatch": 0,
                "by_status": {"MATCHED": 50},
            },
            "grouped_stats": [],
            "key_findings": [],
            "generated_at": "2024-07-07",
            "llm_status": "success",
        }

        async def mock_get_summary(partner, **kwargs):
            if partner == "MOMO":
                raise RuntimeError("MOMO data unavailable")
            return mock_summary

        with patch("src.analysis.insights.get_summary", side_effect=mock_get_summary):
            reporter = DailyReporter(mock_collection, MockLLMProvider())
            report = await reporter.generate_report("2024-07-07")

        # Should only have VIETTEL (MOMO skipped)
        assert len(report["partners"]) == 1
        assert report["partners"][0]["partner"] == "VIETTEL"


class TestDailyReporterSaveReport:
    """Test DailyReporter.save_report()."""

    @pytest.mark.asyncio
    async def test_saves_report_to_disk(self, tmp_path) -> None:
        import json
        from pathlib import Path

        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=[])

        reporter = DailyReporter(mock_collection, MockLLMProvider())

        # Override report directory to temp path
        with patch.object(reporter, "_get_active_partners", return_value=[]):
            report_path = await reporter.save_report("2024-07-07")

        assert report_path.endswith("2024-07-07.json")
        saved_file = Path(report_path)
        assert saved_file.exists()

        with open(saved_file) as f:
            data = json.load(f)
        assert data["date"] == "2024-07-07"
