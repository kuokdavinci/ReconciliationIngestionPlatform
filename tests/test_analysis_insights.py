"""Tests for AI Analysis Layer insights (orchestration)."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analysis.schemas import AnalysisInput, AnalysisResult, SummaryResult, TopAnomaly
from src.analysis.insights import (
    _rule_based_fallback,
    generate_insights,
    get_discrepancies,
    get_summary,
    _query_reconciliation_results,
)


async def empty_async_gen():
    """Async generator that yields nothing."""
    if False:
        yield


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
        self.call_count = 0

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        self.call_count += 1
        if self._should_fail:
            raise RuntimeError("LLM call failed")
        return self._response


class TestQueryReconciliationResults:
    """Test MongoDB query helper."""

    @pytest.mark.asyncio
    async def test_queries_and_converts_results(self) -> None:
        mock_doc = {
            "partner": "MOMO",
            "date": "2024-07-07",
            "partner_amount": Decimal("100000"),
            "internal_amount": Decimal("110000"),
            "reconciliation_status": "AMOUNT_MISMATCH",
        }
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[mock_doc])

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")

        assert len(results) == 1
        assert results[0].partner == "MOMO"
        assert results[0].reconciliation_status.value == "AMOUNT_MISMATCH"

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")
        assert results == []

    @pytest.mark.asyncio
    async def test_handles_unknown_status(self) -> None:
        mock_doc = {
            "partner": "MOMO",
            "date": "2024-07-07",
            "reconciliation_status": "UNKNOWN_STATUS",
        }
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[mock_doc])

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")
        assert len(results) == 1
        # Should default to MATCHED for unknown status
        assert results[0].reconciliation_status.value == "MATCHED"


class TestRuleBasedFallback:
    """Test _rule_based_fallback function."""

    def test_generates_mismatch_rate_insight(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 100,
                "matched": 90,
                "mismatch_rate": 10.0,
                "total_amount_mismatch": 1_000_000,
                "by_status": {"MATCHED": 90, "AMOUNT_MISMATCH": 10},
            },
            grouped_stats=[],
            top_anomalies=[],
        )
        results = _rule_based_fallback(inp)
        # Should have at least the mismatch_rate insight
        types = [r.type for r in results]
        assert "mismatch_rate" in types

    def test_generates_anomaly_insights(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 100,
                "matched": 100,
                "mismatch_rate": 0.0,
                "total_amount_mismatch": 0,
                "by_status": {"MATCHED": 100},
            },
            grouped_stats=[],
            top_anomalies=[
                TopAnomaly(type="missing_internal", count=7, partners_affected=["MOMO"])
            ],
        )
        results = _rule_based_fallback(inp)
        types = [r.type for r in results]
        assert "missing_internal" in types

    def test_generates_missing_internal_insight(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 100,
                "matched": 95,
                "mismatch_rate": 5.0,
                "total_amount_mismatch": 0,
                "by_status": {"MATCHED": 95, "MISSING_INTERNAL": 5},
            },
            grouped_stats=[],
            top_anomalies=[],
        )
        results = _rule_based_fallback(inp)
        types = [r.type for r in results]
        assert "missing_internal" in types

    def test_generates_missing_partner_insight(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 100,
                "matched": 95,
                "mismatch_rate": 5.0,
                "total_amount_mismatch": 0,
                "by_status": {"MATCHED": 95, "MISSING_PARTNER": 5},
            },
            grouped_stats=[],
            top_anomalies=[],
        )
        results = _rule_based_fallback(inp)
        types = [r.type for r in results]
        assert "missing_partner" in types

    def test_no_insights_when_all_matched(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 100,
                "matched": 100,
                "mismatch_rate": 0.0,
                "total_amount_mismatch": 0,
                "by_status": {"MATCHED": 100},
            },
            grouped_stats=[],
            top_anomalies=[],
        )
        results = _rule_based_fallback(inp)
        assert results == []

    def test_severity_scaling(self) -> None:
        """Test severity scales with mismatch rate."""
        for rate, expected_severity in [
            (2.0, "low"),
            (7.0, "medium"),
            (15.0, "high"),
            (25.0, "critical"),
        ]:
            inp = AnalysisInput(
                partner="MOMO",
                date="2024-07-07",
                focus="operational",
                summary_metrics={
                    "total_transactions": 100,
                    "matched": int(100 - rate),
                    "mismatch_rate": rate,
                    "total_amount_mismatch": 0,
                    "by_status": {"MATCHED": int(100 - rate), "AMOUNT_MISMATCH": int(rate)},
                },
                grouped_stats=[],
                top_anomalies=[],
            )
            results = _rule_based_fallback(inp)
            mismatch_result = [r for r in results if r.type == "mismatch_rate"][0]
            assert mismatch_result.severity == expected_severity, f"Rate {rate} should be {expected_severity}"


class TestGenerateInsights:
    """Test generate_insights function."""

    @pytest.mark.asyncio
    async def test_returns_llm_results(self) -> None:
        llm_response = json.dumps({
            "findings": [
                {
                    "type": "operational_delay",
                    "severity": "medium",
                    "title": "Delay detected",
                    "description": "Some delay",
                    "affected_count": 5,
                    "recommendation": "Check pipeline",
                }
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={"total_transactions": 100, "matched": 95, "mismatch_rate": 5.0, "total_amount_mismatch": 0, "by_status": {"MATCHED": 95, "MISSING_INTERNAL": 5}},
            grouped_stats=[],
            top_anomalies=[],
        )

        results = await generate_insights(inp, provider)
        assert len(results) == 1
        assert results[0].type == "operational_delay"
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        provider = MockLLMProvider(should_fail=True)

        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={"total_transactions": 100, "matched": 90, "mismatch_rate": 10.0, "total_amount_mismatch": 0, "by_status": {"MATCHED": 90, "AMOUNT_MISMATCH": 10}},
            grouped_stats=[],
            top_anomalies=[],
        )

        results = await generate_insights(inp, provider)
        # Should return rule-based fallback results
        assert len(results) > 0
        assert any(r.type == "mismatch_rate" for r in results)

    @pytest.mark.asyncio
    async def test_fallback_on_empty_llm_response(self) -> None:
        provider = MockLLMProvider(response="{}")  # No findings key

        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={"total_transactions": 100, "matched": 90, "mismatch_rate": 10.0, "total_amount_mismatch": 0, "by_status": {"MATCHED": 90, "AMOUNT_MISMATCH": 10}},
            grouped_stats=[],
            top_anomalies=[],
        )

        results = await generate_insights(inp, provider)
        # Should return rule-based fallback results
        assert len(results) > 0


class TestGetSummary:
    """Test get_summary orchestration function."""

    @staticmethod
    def _make_mock_collection(docs: list | None = None) -> MagicMock:
        """Create a mock collection supporting both find().limit() and aggregate()."""
        docs = docs or []
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        mock_collection.aggregate = MagicMock(return_value=empty_async_gen())

        return mock_collection

    @pytest.mark.asyncio
    async def test_returns_summary_dict(self) -> None:
        llm_response = json.dumps({
            "findings": [
                {"type": "t", "severity": "low", "title": "Test", "description": "D", "affected_count": 0, "recommendation": ""}
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        mock_collection = self._make_mock_collection()

        result = await get_summary("MOMO", "2024-07-07", mock_collection, provider)

        assert "partner" in result
        assert result["partner"] == "MOMO"
        assert "date" in result
        assert result["date"] == "2024-07-07"
        assert "summary_metrics" in result
        assert "grouped_stats" in result
        assert "key_findings" in result

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        provider = MockLLMProvider(response="{}")

        mock_collection = self._make_mock_collection()

        result = await get_summary("MOMO", "2024-07-07", mock_collection, provider)

        assert result["summary_metrics"]["total_transactions"] == 0
        assert result["summary_metrics"]["matched"] == 0


class TestGetDiscrepancies:
    """Test get_discrepancies orchestration function."""

    @staticmethod
    def _make_mock_collection(docs: list | None = None) -> MagicMock:
        """Create a mock collection supporting both find().limit() and aggregate()."""
        docs = docs or []
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        mock_collection.aggregate = MagicMock(return_value=empty_async_gen())

        return mock_collection

    @pytest.mark.asyncio
    async def test_returns_analysis_results(self) -> None:
        llm_response = json.dumps({
            "findings": [
                {"type": "operational_delay", "severity": "medium", "title": "Delay", "description": "D", "affected_count": 5, "recommendation": "R"}
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        mock_collection = self._make_mock_collection()

        results = await get_discrepancies("MOMO", "2024-07-07", "operational", mock_collection, provider)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        provider = MockLLMProvider(should_fail=True)

        mock_collection = self._make_mock_collection()

        results = await get_discrepancies("MOMO", "2024-07-07", "operational", mock_collection, provider)

        # Should return rule-based fallback (empty since no results)
        assert isinstance(results, list)
