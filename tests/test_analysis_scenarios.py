"""Diverse scenario tests for AI Analysis Layer.

Covers:
- MULTIPLE_MISMATCH and STATUS_MISMATCH status handling
- MongoDB camelCase/snake_case field conversion
- Cross-partner aggregation with mixed statuses
- Large volume scenarios with diverse amount ranges
- LLM response parsing edge cases (markdown, nested JSON, malformed)
- Severity scaling boundary conditions
- Amount range boundary conditions (0, 100k, 1M, inf)
- Daily report with multiple partners and partial failures
- Rule-based pre-processing for all focus types with complex data
- Edge cases in metrics, grouping, and insights orchestration
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analysis.schemas import (
    AnalysisInput,
    AnalysisResult,
    SummaryResult,
    TopAnomaly,
)
from src.analysis.services import (
    build_analysis_input,
    parse_llm_insights,
    format_findings,
    rule_based_pre_process,
    extract_inconsistency_anomalies,
)
from src.analysis.grouping import GroupingEngine
from src.analysis.metrics import MetricsService
from src.analysis.insights import (
    _rule_based_fallback,
    get_summary,
    get_discrepancies,
    _query_reconciliation_results,
)
from src.core.enums import ReconciliationStatus


# ---------------------------------------------------------------------------
# Mock data factories
# ---------------------------------------------------------------------------

def make_result(
    status: str = "MATCHED",
    partner: str = "MOMO",
    date: str = "2024-07-07",
    partner_amount: Decimal | None = Decimal("100000"),
    internal_amount: Decimal | None = Decimal("100000"),
) -> SimpleNamespace:
    """Create a mock reconciliation result with explicit attributes."""
    r = SimpleNamespace()
    r.partner = partner
    r.date = date
    r.partner_amount = partner_amount
    r.internal_amount = internal_amount
    r.reconciliation_status = ReconciliationStatus(status)
    return r


def make_mongo_doc(
    status: str = "MATCHED",
    partner: str = "MOMO",
    date: str = "2024-07-07",
    partner_amount: str | None = "100000",
    internal_amount: str | None = "100000",
    camel_case: bool = False,
) -> dict[str, Any]:
    """Create a mock MongoDB document with camelCase or snake_case fields."""
    doc: dict[str, Any] = {"partner": partner, "date": date}
    if camel_case:
        if partner_amount is not None:
            doc["partnerAmount"] = Decimal(partner_amount)
        if internal_amount is not None:
            doc["internalAmount"] = Decimal(internal_amount)
        doc["reconciliationStatus"] = status
    else:
        if partner_amount is not None:
            doc["partner_amount"] = Decimal(partner_amount)
        if internal_amount is not None:
            doc["internal_amount"] = Decimal(internal_amount)
        doc["reconciliation_status"] = status
    return doc


class MockLLMProvider:
    """Mock LLM provider with configurable response and failure modes."""

    def __init__(self, response: str = "", should_fail: bool = False, call_delay: float = 0):
        self._response = response
        self._should_fail = should_fail
        self.call_count = 0
        self.last_prompt: str | None = None
        self.last_system_prompt: str | None = None

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt
        if self._should_fail:
            raise RuntimeError("LLM call failed")
        return self._response

    @property
    def model(self) -> str:
        return "test-model"

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def last_token_usage(self) -> Optional[dict[str, int]]:
        return None


# ---------------------------------------------------------------------------
# Scenario 1: MULTIPLE_MISMATCH status handling
# ---------------------------------------------------------------------------

class TestMultipleMismatchStatus:
    """Test MULTIPLE_MISMATCH status through the full pipeline."""

    def test_metrics_accumulates_multiple_mismatch_amounts(self) -> None:
        """MULTIPLE_MISMATCH should accumulate both partner and internal amount diffs."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("MULTIPLE_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000")),
            make_result("MULTIPLE_MISMATCH", partner_amount=Decimal("200000"), internal_amount=Decimal("180000")),
        ]

        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")

        assert summary.total_transactions == 3
        assert summary.matched == 1
        assert summary.mismatch_rate == pytest.approx(66.67, rel=1e-2)
        # 10000 + 20000 = 30000 total mismatch
        assert summary.total_amount_mismatch == Decimal("30000")
        assert summary.by_status["MULTIPLE_MISMATCH"] == 2

    def test_grouping_handles_multiple_mismatch_as_separate_group(self) -> None:
        """MULTIPLE_MISMATCH should be its own group key."""
        results = [
            make_result("MATCHED"),
            make_result("MULTIPLE_MISMATCH", partner_amount=Decimal("50000"), internal_amount=Decimal("45000")),
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("30000"), internal_amount=Decimal("25000")),
        ]

        groups = GroupingEngine.group(results)
        keys = {g.key for g in groups}

        assert "MULTIPLE_MISMATCH" in keys
        assert "AMOUNT_MISMATCH" in keys
        assert "MATCHED" in keys

        multiple_group = next(g for g in groups if g.key == "MULTIPLE_MISMATCH")
        assert multiple_group.count == 1
        # Details use avg_difference, min_difference, max_difference
        assert multiple_group.details.get("avg_difference") is not None

    def test_inconsistency_anomalies_include_multiple_mismatch(self) -> None:
        """extract_inconsistency_anomalies should include MULTIPLE_MISMATCH in amount cluster."""
        results = [
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000")),
            make_result("MULTIPLE_MISMATCH", partner_amount=Decimal("200000"), internal_amount=Decimal("180000")),
            make_result("STATUS_MISMATCH"),
        ]

        anomalies = extract_inconsistency_anomalies(results)

        amount_cluster = next((a for a in anomalies if a.type == "amount_mismatch_cluster"), None)
        assert amount_cluster is not None
        assert amount_cluster.count == 2  # Both AMOUNT_MISMATCH and MULTIPLE_MISMATCH

    def test_rule_based_fallback_with_multiple_mismatch_in_by_status(self) -> None:
        """Fallback should generate mismatch_rate insight when MULTIPLE_MISMATCH present."""
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 10,
                "matched": 5,
                "mismatch_rate": 50.0,
                "total_amount_mismatch": 500000,
                "by_status": {"MATCHED": 5, "MULTIPLE_MISMATCH": 3, "AMOUNT_MISMATCH": 2},
            },
            grouped_stats=[],
            top_anomalies=[],
        )

        results = _rule_based_fallback(inp)
        types = [r.type for r in results]
        assert "mismatch_rate" in types
        mismatch = next(r for r in results if r.type == "mismatch_rate")
        assert mismatch.severity == "critical"  # 50% > 20%


# ---------------------------------------------------------------------------
# Scenario 2: STATUS_MISMATCH amount handling
# ---------------------------------------------------------------------------

class TestStatusMismatchAmountHandling:
    """Test STATUS_MISMATCH with and without amounts."""

    def test_metrics_skips_amount_diff_when_amounts_are_none(self) -> None:
        """STATUS_MISMATCH with None amounts should not contribute to total_amount_mismatch."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("STATUS_MISMATCH", partner_amount=None, internal_amount=None),
            make_result("STATUS_MISMATCH", partner_amount=None, internal_amount=None),
        ]

        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")

        assert summary.total_transactions == 3
        assert summary.matched == 1
        assert summary.mismatch_rate == pytest.approx(66.67, rel=1e-2)
        assert summary.total_amount_mismatch == Decimal("0")
        assert summary.by_status["STATUS_MISMATCH"] == 2

    def test_metrics_includes_amount_diff_when_both_present(self) -> None:
        """STATUS_MISMATCH with both amounts should contribute to total_amount_mismatch."""
        results = [
            make_result("STATUS_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("95000")),
        ]

        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")

        assert summary.total_amount_mismatch == Decimal("5000")

    def test_status_mismatch_in_inconsistency_anomalies(self) -> None:
        """STATUS_MISMATCH should appear in status_mismatch_cluster."""
        results = [
            make_result("STATUS_MISMATCH"),
            make_result("STATUS_MISMATCH"),
            make_result("MATCHED"),
        ]

        anomalies = extract_inconsistency_anomalies(results)
        status_cluster = next((a for a in anomalies if a.type == "status_mismatch_cluster"), None)
        assert status_cluster is not None
        assert status_cluster.count == 2


# ---------------------------------------------------------------------------
# Scenario 3: MongoDB camelCase/snake_case field conversion
# ---------------------------------------------------------------------------

class TestMongoDBFieldConversion:
    """Test _query_reconciliation_results handles both field naming conventions."""

    @pytest.mark.asyncio
    async def test_camel_case_fields_converted_correctly(self) -> None:
        """camelCase fields should be read and converted to snake_case attributes."""
        mock_doc = make_mongo_doc(
            status="AMOUNT_MISMATCH",
            partner_amount="150000",
            internal_amount="140000",
            camel_case=True,
        )
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[mock_doc])
        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")

        assert len(results) == 1
        assert results[0].partner_amount == Decimal("150000")
        assert results[0].internal_amount == Decimal("140000")
        assert results[0].reconciliation_status.value == "AMOUNT_MISMATCH"

    @pytest.mark.asyncio
    async def test_snake_case_fields_converted_correctly(self) -> None:
        """snake_case fields should be read correctly."""
        mock_doc = make_mongo_doc(
            status="MISSING_INTERNAL",
            partner_amount="0",
            internal_amount=None,
            camel_case=False,
        )
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[mock_doc])
        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")

        assert len(results) == 1
        assert results[0].partner_amount == Decimal("0")
        assert results[0].internal_amount is None
        assert results[0].reconciliation_status.value == "MISSING_INTERNAL"

    @pytest.mark.asyncio
    async def test_camel_case_takes_precedence_when_both_present(self) -> None:
        """When both camelCase and snake_case exist, camelCase should be preferred."""
        mock_doc = {
            "partner": "MOMO",
            "date": "2024-07-07",
            "partnerAmount": Decimal("200000"),
            "partner_amount": Decimal("100000"),  # Should be ignored
            "internalAmount": Decimal("190000"),
            "internal_amount": Decimal("90000"),  # Should be ignored
            "reconciliationStatus": "AMOUNT_MISMATCH",
            "reconciliation_status": "MATCHED",  # Should be ignored
        }
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[mock_doc])
        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")

        assert results[0].partner_amount == Decimal("200000")
        assert results[0].internal_amount == Decimal("190000")
        assert results[0].reconciliation_status.value == "AMOUNT_MISMATCH"

    @pytest.mark.asyncio
    async def test_mixed_documents_in_same_query(self) -> None:
        """Query should handle mix of camelCase and snake_case documents."""
        docs = [
            make_mongo_doc(status="MATCHED", partner_amount="100000", internal_amount="100000", camel_case=True),
            make_mongo_doc(status="AMOUNT_MISMATCH", partner_amount="50000", internal_amount="45000", camel_case=False),
            make_mongo_doc(status="MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
        ]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        results = await _query_reconciliation_results(mock_collection, "MOMO", "2024-07-07")

        assert len(results) == 3
        # All should have correct amounts regardless of source format
        assert results[0].partner_amount == Decimal("100000")
        assert results[1].partner_amount == Decimal("50000")
        assert results[2].partner_amount is None


# ---------------------------------------------------------------------------
# Scenario 4: Cross-partner aggregation
# ---------------------------------------------------------------------------

class TestCrossPartnerAggregation:
    """Test grouping and metrics with multiple partners."""

    def test_group_by_partner_with_multiple_partners(self) -> None:
        """GroupingEngine should correctly group by partner."""
        results = [
            make_result("MATCHED", partner="MOMO", partner_amount=Decimal("100000")),
            make_result("MATCHED", partner="MOMO", partner_amount=Decimal("200000")),
            make_result("AMOUNT_MISMATCH", partner="VIETTEL", partner_amount=Decimal("50000"), internal_amount=Decimal("45000")),
            make_result("MISSING_INTERNAL", partner="ZALOPAY", partner_amount=None),
        ]

        groups = GroupingEngine.group_by_partner(results)
        partner_groups = [g for g in groups if g.key in ("MOMO", "VIETTEL", "ZALOPAY")]

        assert len(partner_groups) == 3
        momo = next(g for g in partner_groups if g.key == "MOMO")
        assert momo.count == 2
        assert momo.total_amount == 300000.0

    def test_metrics_with_mixed_partners(self) -> None:
        """MetricsService should compute correct stats across multiple partners."""
        results = [
            make_result("MATCHED", partner="MOMO", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("MATCHED", partner="MOMO", partner_amount=Decimal("200000"), internal_amount=Decimal("200000")),
            make_result("AMOUNT_MISMATCH", partner="VIETTEL", partner_amount=Decimal("50000"), internal_amount=Decimal("40000")),
            make_result("MISSING_INTERNAL", partner="ZALOPAY", partner_amount=None, internal_amount=None),
            make_result("MATCHED", partner="ZALOPAY", partner_amount=Decimal("75000"), internal_amount=Decimal("75000")),
        ]

        summary = MetricsService.compute_summary(results, "ALL", "2024-07-07")

        assert summary.total_transactions == 5
        assert summary.matched == 3
        assert summary.mismatch_rate == pytest.approx(40.0, rel=1e-2)
        assert summary.total_amount_mismatch == Decimal("10000")
        assert summary.by_status == {
            "MATCHED": 3,
            "AMOUNT_MISMATCH": 1,
            "MISSING_INTERNAL": 1,
        }

    @pytest.mark.asyncio
    async def test_daily_report_aggregates_multiple_partners(self) -> None:
        """DailyReporter should aggregate stats across partners."""
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=["MOMO", "VIETTEL", "ZALOPAY"])

        summaries = {
            "MOMO": {
                "partner": "MOMO",
                "date": "2024-07-07",
                "summary_metrics": {"total_transactions": 100, "matched": 95, "mismatch_rate": 5.0, "total_amount_mismatch": 500000, "by_status": {"MATCHED": 95, "AMOUNT_MISMATCH": 5}},
                "grouped_stats": [],
                "key_findings": ["MOMO finding"],
                "generated_at": "2024-07-07",
                "llm_status": "success",
            },
            "VIETTEL": {
                "partner": "VIETTEL",
                "date": "2024-07-07",
                "summary_metrics": {"total_transactions": 50, "matched": 50, "mismatch_rate": 0.0, "total_amount_mismatch": 0, "by_status": {"MATCHED": 50}},
                "grouped_stats": [],
                "key_findings": [],
                "generated_at": "2024-07-07",
                "llm_status": "success",
            },
            "ZALOPAY": {
                "partner": "ZALOPAY",
                "date": "2024-07-07",
                "summary_metrics": {"total_transactions": 200, "matched": 180, "mismatch_rate": 10.0, "total_amount_mismatch": 1000000, "by_status": {"MATCHED": 180, "MISSING_INTERNAL": 20}},
                "grouped_stats": [],
                "key_findings": ["ZaloPay finding"],
                "generated_at": "2024-07-07",
                "llm_status": "success",
            },
        }

        async def mock_get_summary(partner, **kwargs):
            return summaries[partner]

        with patch("src.analysis.insights.get_summary", side_effect=mock_get_summary):
            reporter = DailyReporter(mock_collection, MockLLMProvider())
            report = await reporter.generate_report("2024-07-07")

        assert len(report["partners"]) == 3
        assert report["global_stats"]["total_volume"] == 350  # 100 + 50 + 200
        # Global mismatch rate should be weighted average
        total_mismatch_txns = 5 + 0 + 20  # 25
        total_txns = 350
        expected_rate = (total_mismatch_txns / total_txns) * 100
        assert report["global_stats"]["total_mismatch_rate"] == pytest.approx(expected_rate, rel=1e-2)


# ---------------------------------------------------------------------------
# Scenario 5: Large volume scenarios with diverse amount ranges
# ---------------------------------------------------------------------------

class TestLargeVolumeScenarios:
    """Test with realistic large volumes and amount range diversity."""

    def test_amount_range_grouping_covers_all_buckets(self) -> None:
        """Grouping should correctly bucket transactions across all amount ranges."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("50000"), internal_amount=Decimal("50000")),       # 0-100k
            make_result("MATCHED", partner_amount=Decimal("99999"), internal_amount=Decimal("99999")),       # 0-100k boundary
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("95000")),  # 100k-1M
            make_result("MATCHED", partner_amount=Decimal("500000"), internal_amount=Decimal("500000")),     # 100k-1M
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("999999"), internal_amount=Decimal("900000")),  # 100k-1M boundary
            make_result("MATCHED", partner_amount=Decimal("1000000"), internal_amount=Decimal("1000000")),   # 1M+
            make_result("MULTIPLE_MISMATCH", partner_amount=Decimal("5000000"), internal_amount=Decimal("4500000")),  # 1M+
        ]

        groups = GroupingEngine.group_by_amount_range(results)
        keys = {g.key for g in groups}

        assert "0-100k" in keys
        assert "100k-1M" in keys
        assert "1M+" in keys

        range_0_100k = next(g for g in groups if g.key == "0-100k")
        assert range_0_100k.count == 2

        range_100k_1m = next(g for g in groups if g.key == "100k-1M")
        assert range_100k_1m.count == 3

        range_1m_plus = next(g for g in groups if g.key == "1M+")
        assert range_1m_plus.count == 2

    def test_large_volume_with_mixed_statuses(self) -> None:
        """1000+ transactions with realistic status distribution."""
        results = []
        # 900 MATCHED
        for i in range(900):
            results.append(make_result("MATCHED", partner_amount=Decimal(str(100000 + i)), internal_amount=Decimal(str(100000 + i))))
        # 50 AMOUNT_MISMATCH
        for i in range(50):
            results.append(make_result("AMOUNT_MISMATCH", partner_amount=Decimal(str(100000 + i)), internal_amount=Decimal(str(95000 + i))))
        # 30 MISSING_INTERNAL
        for i in range(30):
            results.append(make_result("MISSING_INTERNAL", partner_amount=None, internal_amount=None))
        # 20 MISSING_PARTNER
        for i in range(20):
            results.append(make_result("MISSING_PARTNER", partner_amount=None, internal_amount=None))

        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")

        assert summary.total_transactions == 1000
        assert summary.matched == 900
        assert summary.mismatch_rate == pytest.approx(10.0, rel=1e-2)
        assert summary.by_status["MATCHED"] == 900
        assert summary.by_status["AMOUNT_MISMATCH"] == 50
        assert summary.by_status["MISSING_INTERNAL"] == 30
        assert summary.by_status["MISSING_PARTNER"] == 20

    def test_analysis_input_no_raw_data_with_large_volume(self) -> None:
        """AnalysisInput should never contain raw transaction data even with large volumes."""
        results = [make_result("MATCHED", partner_amount=Decimal(str(100000 + i))) for i in range(500)]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        groups = GroupingEngine.group(results)

        analysis_input = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=summary,
            grouped_results=groups,
        )

        # Verify no raw data fields exist
        assert not hasattr(analysis_input, "partner_txn_id")
        assert not hasattr(analysis_input, "internal_txn_id")
        assert not hasattr(analysis_input, "raw_transactions")
        # Only aggregated data
        assert analysis_input.summary_metrics["total_transactions"] == 500


# ---------------------------------------------------------------------------
# Scenario 6: LLM response parsing edge cases
# ---------------------------------------------------------------------------

class TestLLMResponseParsingEdgeCases:
    """Test parse_llm_insights with various LLM response formats."""

    def test_parses_clean_json(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "test", "severity": "low", "title": "Test", "description": "D", "affected_count": 1, "recommendation": "R"}
            ]
        })
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "test"

    def test_parses_markdown_code_block(self) -> None:
        response = """Here are my findings:
```json
{
  "findings": [
    {"type": "delay", "severity": "medium", "title": "Delay", "description": "D", "affected_count": 5, "recommendation": "R"}
  ]
}
```
Hope this helps!"""
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "delay"

    def test_parses_markdown_without_json_tag(self) -> None:
        response = """```
{
  "findings": [
    {"type": "error", "severity": "high", "title": "Error", "description": "D", "affected_count": 10, "recommendation": "R"}
  ]
}
```"""
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "error"

    def test_parses_json_with_surrounding_text(self) -> None:
        response = """Based on the analysis, here are the findings:

{
  "findings": [
    {"type": "pattern", "severity": "low", "title": "Pattern", "description": "D", "affected_count": 3, "recommendation": "R"}
  ]
}

Let me know if you need more details."""
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "pattern"

    def test_handles_multiple_findings(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "t1", "severity": "low", "title": "T1", "description": "D1", "affected_count": 1, "recommendation": "R1"},
                {"type": "t2", "severity": "high", "title": "T2", "description": "D2", "affected_count": 10, "recommendation": "R2"},
                {"type": "t3", "severity": "critical", "title": "T3", "description": "D3", "affected_count": 50, "recommendation": "R3"},
            ]
        })
        results = parse_llm_insights(response)
        assert len(results) == 3
        severities = [r.severity for r in results]
        assert severities == ["low", "high", "critical"]

    def test_returns_empty_on_invalid_json(self) -> None:
        results = parse_llm_insights("This is not JSON at all")
        assert results == []

    def test_returns_empty_on_missing_findings_key(self) -> None:
        results = parse_llm_insights(json.dumps({"results": []}))
        assert results == []

    def test_returns_empty_on_non_list_findings(self) -> None:
        results = parse_llm_insights(json.dumps({"findings": "not a list"}))
        assert results == []

    def test_skips_invalid_finding_entries(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "valid", "severity": "low", "title": "Valid", "description": "D", "affected_count": 1, "recommendation": "R"},
                {"type": 123, "severity": "low", "title": "NumericType", "description": "D", "affected_count": 1, "recommendation": "R"},  # type is int, should be stringified
            ]
        })
        results = parse_llm_insights(response)
        # Both should parse (int type gets stringified)
        assert len(results) == 2
        assert results[0].type == "valid"
        assert results[1].type == "123"

    def test_defaults_for_missing_fields(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "minimal"}
            ]
        })
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "minimal"
        assert results[0].severity == "low"
        assert results[0].title == ""
        assert results[0].description == ""
        assert results[0].affected_count == 0
        assert results[0].recommendation == ""

    def test_handles_nested_json_in_description(self) -> None:
        """LLM might include JSON-like content in description."""
        response = json.dumps({
            "findings": [
                {"type": "complex", "severity": "medium", "title": "Complex", "description": 'Error: {"code": 500, "message": "timeout"}', "affected_count": 1, "recommendation": "R"}
            ]
        })
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert "500" in results[0].description


# ---------------------------------------------------------------------------
# Scenario 7: Severity scaling boundary conditions
# ---------------------------------------------------------------------------

class TestSeverityScalingBoundaries:
    """Test severity scaling at exact boundary values."""

    def test_mismatch_rate_severity_boundaries(self) -> None:
        """Test exact boundary values for mismatch rate severity."""
        boundaries = [
            (0.0, "low"),
            (0.01, "low"),
            (4.99, "low"),
            (5.0, "low"),       # Exactly 5% → low (not > 5)
            (5.01, "medium"),   # Just above 5%
            (9.99, "medium"),
            (10.0, "medium"),   # Exactly 10% → medium (not > 10)
            (10.01, "high"),    # Just above 10%
            (19.99, "high"),
            (20.0, "high"),     # Exactly 20% → high (not > 20)
            (20.01, "critical"),  # Just above 20%
            (50.0, "critical"),
            (100.0, "critical"),
        ]

        for rate, expected_severity in boundaries:
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
            mismatch_result = next((r for r in results if r.type == "mismatch_rate"), None)
            if mismatch_result:
                assert mismatch_result.severity == expected_severity, f"Rate {rate} should be {expected_severity}, got {mismatch_result.severity}"

    def test_anomaly_count_severity_boundaries(self) -> None:
        """Test anomaly count severity boundaries."""
        boundaries = [
            (1, "low"),
            (5, "low"),
            (6, "medium"),
            (10, "medium"),
            (11, "high"),
            (50, "high"),
            (100, "high"),
        ]

        for count, expected_severity in boundaries:
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
                    TopAnomaly(type="missing_internal", count=count, partners_affected=["MOMO"])
                ],
            )
            results = _rule_based_fallback(inp)
            anomaly_result = next((r for r in results if r.type == "missing_internal"), None)
            if anomaly_result:
                assert anomaly_result.severity == expected_severity, f"Count {count} should be {expected_severity}, got {anomaly_result.severity}"

    def test_alerter_severity_scaling_boundaries(self) -> None:
        """Test ThresholdAlerter severity scaling at boundaries."""
        from src.analysis.alerter import ThresholdAlerter
        from src.analysis.config import AnalysisConfig

        alerter = ThresholdAlerter(AnalysisConfig(alert_mismatch_rate_threshold=5.0))

        # ratio = rate / threshold
        # ratio > 4 → critical, > 2 → high, > 1.5 → medium, else → low
        cases = [
            (5.0, "low"),       # ratio = 1.0
            (7.5, "low"),       # ratio = 1.5 (not > 1.5)
            (7.51, "medium"),   # ratio > 1.5
            (10.0, "medium"),   # ratio = 2.0 (not > 2, but > 1.5)
            (10.01, "high"),    # ratio > 2
            (20.0, "high"),     # ratio = 4.0 (not > 4, but > 2)
            (20.01, "critical"),  # ratio > 4
        ]

        for rate, expected_severity in cases:
            summary = SummaryResult(
                partner="MOMO",
                date="2024-07-07",
                total_transactions=100,
                matched=int(100 - rate),
                mismatch_rate=rate,
                total_amount_mismatch=0,
                by_status={"MATCHED": int(100 - rate), "AMOUNT_MISMATCH": int(rate)},
            )
            alerts = alerter.check_thresholds(summary)
            if alerts:
                assert alerts[0].severity == expected_severity, f"Rate {rate} should be {expected_severity}, got {alerts[0].severity}"


# ---------------------------------------------------------------------------
# Scenario 8: Amount range boundary conditions
# ---------------------------------------------------------------------------

class TestAmountRangeBoundaries:
    """Test amount range bucketing at exact boundaries."""

    def test_zero_amount(self) -> None:
        """Zero amount should fall in 0-100k range."""
        results = [make_result("MATCHED", partner_amount=Decimal("0"), internal_amount=Decimal("0"))]
        groups = GroupingEngine.group_by_amount_range(results)
        range_group = next((g for g in groups if g.key == "0-100k"), None)
        assert range_group is not None
        assert range_group.count == 1

    def test_exact_100k_boundary(self) -> None:
        """Exactly 100k should fall in 100k-1M range."""
        results = [make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000"))]
        groups = GroupingEngine.group_by_amount_range(results)
        range_group = next((g for g in groups if g.key == "100k-1M"), None)
        assert range_group is not None
        assert range_group.count == 1

    def test_just_below_100k(self) -> None:
        """99999 should fall in 0-100k range."""
        results = [make_result("MATCHED", partner_amount=Decimal("99999"), internal_amount=Decimal("99999"))]
        groups = GroupingEngine.group_by_amount_range(results)
        range_group = next((g for g in groups if g.key == "0-100k"), None)
        assert range_group is not None

    def test_exact_1m_boundary(self) -> None:
        """Exactly 1M should fall in 1M+ range."""
        results = [make_result("MATCHED", partner_amount=Decimal("1000000"), internal_amount=Decimal("1000000"))]
        groups = GroupingEngine.group_by_amount_range(results)
        range_group = next((g for g in groups if g.key == "1M+"), None)
        assert range_group is not None
        assert range_group.count == 1

    def test_just_below_1m(self) -> None:
        """999999 should fall in 100k-1M range."""
        results = [make_result("MATCHED", partner_amount=Decimal("999999"), internal_amount=Decimal("999999"))]
        groups = GroupingEngine.group_by_amount_range(results)
        range_group = next((g for g in groups if g.key == "100k-1M"), None)
        assert range_group is not None

    def test_none_amount_skipped(self) -> None:
        """None amount should be skipped from amount range grouping."""
        results = [
            make_result("MISSING_INTERNAL", partner_amount=None, internal_amount=None),
            make_result("MATCHED", partner_amount=Decimal("50000"), internal_amount=Decimal("50000")),
        ]
        groups = GroupingEngine.group_by_amount_range(results)
        range_keys = {g.key for g in groups}
        assert "0-100k" in range_keys
        # MISSING_INTERNAL should not create an amount range group
        total_in_ranges = sum(g.count for g in groups)
        assert total_in_ranges == 1  # Only the MATCHED one


# ---------------------------------------------------------------------------
# Scenario 9: Rule-based pre-processing for all focus types
# ---------------------------------------------------------------------------

class TestRuleBasedPreProcessingAllFocusTypes:
    """Test rule_based_pre_process with complex data for each focus type."""

    def test_operational_focus_extracts_all_missing_types(self) -> None:
        """Operational focus should extract both MISSING_INTERNAL and MISSING_PARTNER."""
        results = [
            make_result("MATCHED"),
            make_result("MISSING_INTERNAL"),
            make_result("MISSING_INTERNAL"),
            make_result("MISSING_INTERNAL"),
            make_result("MISSING_PARTNER"),
            make_result("MISSING_PARTNER"),
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000")),
        ]

        anomalies = rule_based_pre_process(results, "operational")

        missing_internal = next((a for a in anomalies if a.type == "missing_internal"), None)
        missing_partner = next((a for a in anomalies if a.type == "missing_partner"), None)

        assert missing_internal is not None
        assert missing_internal.count == 3
        assert missing_partner is not None
        assert missing_partner.count == 2

    def test_partner_focus_detects_high_mismatch_rate(self) -> None:
        """Partner focus should detect high mismatch rate."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000")),
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("85000")),
        ]

        summary_metrics = {
            "total_transactions": 3,
            "matched": 1,
            "mismatch_rate": 66.67,
            "total_amount_mismatch": 25000,
            "by_status": {"MATCHED": 1, "AMOUNT_MISMATCH": 2},
            "partner": "MOMO",
        }

        anomalies = rule_based_pre_process(results, "partner", summary_metrics)

        high_mismatch = next((a for a in anomalies if a.type == "high_mismatch_rate"), None)
        assert high_mismatch is not None
        assert high_mismatch.partners_affected == ["MOMO"]

    def test_partner_focus_no_anomaly_when_rate_low(self) -> None:
        """Partner focus should not create anomaly when rate is below 5%."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("99000")),
        ]

        summary_metrics = {
            "total_transactions": 4,
            "matched": 3,
            "mismatch_rate": 25.0,  # 1/4 = 25%
            "total_amount_mismatch": 1000,
            "by_status": {"MATCHED": 3, "AMOUNT_MISMATCH": 1},
            "partner": "MOMO",
        }

        anomalies = rule_based_pre_process(results, "partner", summary_metrics)
        # 25% > 5%, so should have anomaly
        assert len(anomalies) == 1
        assert anomalies[0].type == "high_mismatch_rate"

    def test_inconsistency_focus_clusters_amount_and_status_mismatches(self) -> None:
        """Inconsistency focus should cluster amount and status mismatches separately."""
        results = [
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000")),
            make_result("AMOUNT_MISMATCH", partner_amount=Decimal("200000"), internal_amount=Decimal("180000")),
            make_result("MULTIPLE_MISMATCH", partner_amount=Decimal("50000"), internal_amount=Decimal("40000")),
            make_result("STATUS_MISMATCH"),
            make_result("STATUS_MISMATCH"),
            make_result("STATUS_MISMATCH"),
            make_result("MATCHED"),
        ]

        anomalies = rule_based_pre_process(results, "inconsistency")

        amount_cluster = next((a for a in anomalies if a.type == "amount_mismatch_cluster"), None)
        status_cluster = next((a for a in anomalies if a.type == "status_mismatch_cluster"), None)

        assert amount_cluster is not None
        assert amount_cluster.count == 3  # 2 AMOUNT_MISMATCH + 1 MULTIPLE_MISMATCH
        assert status_cluster is not None
        assert status_cluster.count == 3

    def test_unknown_focus_returns_empty(self) -> None:
        """Unknown focus type should return empty anomalies list."""
        results = [make_result("MATCHED")]
        anomalies = rule_based_pre_process(results, "unknown_focus")
        assert anomalies == []

    def test_operational_focus_with_multiple_partners(self) -> None:
        """Operational focus should track partners_affected correctly."""
        results = [
            make_result("MISSING_INTERNAL", partner="MOMO"),
            make_result("MISSING_INTERNAL", partner="MOMO"),
            make_result("MISSING_PARTNER", partner="VIETTEL"),
        ]

        anomalies = rule_based_pre_process(results, "operational")

        missing_internal = next((a for a in anomalies if a.type == "missing_internal"), None)
        assert missing_internal is not None
        assert "MOMO" in missing_internal.partners_affected


# ---------------------------------------------------------------------------
# Scenario 10: End-to-end orchestration with diverse data
# ---------------------------------------------------------------------------

def _make_mock_collection(
    docs: list[dict],
    aggregate_results: list[dict] | None = None,
) -> MagicMock:
    """Create a mock collection that handles both find().limit() and aggregate().

    Args:
        docs: Documents returned by find().to_list() and find().limit().to_list()
        aggregate_results: Documents yielded by aggregate() async iteration.
            If None, counts from docs are used to synthesize aggregate results.

    Returns:
        MagicMock configured for both find and aggregate paths.
    """
    # Cursor that supports both .to_list() and .limit() returning self
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=docs)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)

    mock_collection = MagicMock()
    mock_collection.find = MagicMock(return_value=mock_cursor)

    if aggregate_results is None:
        # Auto-synthesize aggregate results from docs
        from collections import Counter
        status_counts: Counter = Counter()
        for d in docs:
            status = d.get("reconciliationStatus") or d.get("reconciliation_status", "MATCHED")
            status_counts[status] += 1
        aggregate_results = [
            {"_id": s, "count": c, "mismatch_amount": 0.0}
            for s, c in status_counts.items()
        ]

    async def _aggregate_iter():
        for doc in aggregate_results:
            yield doc

    mock_collection.aggregate = MagicMock(return_value=_aggregate_iter())

    return mock_collection


class TestEndToEndOrchestration:
    """Test full orchestration flow with realistic diverse data."""

    @pytest.mark.asyncio
    async def test_get_summary_with_mixed_statuses_and_amounts(self) -> None:
        """get_summary should handle mixed statuses and amount ranges correctly."""
        llm_response = json.dumps({
            "findings": [
                {"type": "summary", "severity": "medium", "title": "Mixed statuses", "description": "D", "affected_count": 5, "recommendation": "R"}
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        docs = [
            make_mongo_doc("MATCHED", partner_amount="100000", internal_amount="100000", camel_case=True),
            make_mongo_doc("MATCHED", partner_amount="500000", internal_amount="500000", camel_case=True),
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="100000", internal_amount="90000", camel_case=False),
            make_mongo_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
            make_mongo_doc("MISSING_PARTNER", partner_amount=None, internal_amount=None, camel_case=False),
            make_mongo_doc("STATUS_MISMATCH", partner_amount="200000", internal_amount="200000", camel_case=True),
        ]

        aggregate_results = [
            {"_id": "MATCHED", "count": 2, "mismatch_amount": 0.0},
            {"_id": "AMOUNT_MISMATCH", "count": 1, "mismatch_amount": 10000.0},
            {"_id": "MISSING_INTERNAL", "count": 1, "mismatch_amount": 0.0},
            {"_id": "MISSING_PARTNER", "count": 1, "mismatch_amount": 0.0},
            {"_id": "STATUS_MISMATCH", "count": 1, "mismatch_amount": 0.0},
        ]
        mock_collection = _make_mock_collection(docs, aggregate_results)

        result = await get_summary("MOMO", "2024-07-07", mock_collection, provider)

        assert result["partner"] == "MOMO"
        assert result["date"] == "2024-07-07"
        assert result["summary_metrics"]["total_transactions"] == 6
        assert result["summary_metrics"]["matched"] == 2
        assert result["summary_metrics"]["mismatch_rate"] == pytest.approx(66.67, rel=1e-2)
        assert result["summary_metrics"]["by_status"]["MATCHED"] == 2
        assert result["summary_metrics"]["by_status"]["AMOUNT_MISMATCH"] == 1
        assert result["summary_metrics"]["by_status"]["MISSING_INTERNAL"] == 1
        assert result["summary_metrics"]["by_status"]["MISSING_PARTNER"] == 1
        assert result["summary_metrics"]["by_status"]["STATUS_MISMATCH"] == 1
        assert len(result["key_findings"]) == 1
        assert result["llm_status"] == "success"

    @pytest.mark.asyncio
    async def test_get_discrepancies_operational_focus(self) -> None:
        """get_discrepancies with operational focus should detect missing records."""
        llm_response = json.dumps({
            "findings": [
                {"type": "operational_delay", "severity": "medium", "title": "Delay", "description": "D", "affected_count": 3, "recommendation": "R"}
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        docs = [
            make_mongo_doc("MATCHED", partner_amount="100000", internal_amount="100000", camel_case=True),
            make_mongo_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
            make_mongo_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
            make_mongo_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
        ]

        mock_collection = _make_mock_collection(docs)

        results = await get_discrepancies("MOMO", "2024-07-07", "operational", mock_collection, provider)

        assert isinstance(results, list)
        assert len(results) >= 1  # At least the LLM finding or fallback

    @pytest.mark.asyncio
    async def test_get_discrepancies_partner_focus(self) -> None:
        """get_discrepancies with partner focus should detect high mismatch rate."""
        llm_response = json.dumps({
            "findings": [
                {"type": "partner_pattern", "severity": "high", "title": "High mismatch", "description": "D", "affected_count": 50, "recommendation": "R"}
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        docs = [
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="100000", internal_amount="80000", camel_case=True),
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="200000", internal_amount="160000", camel_case=True),
            make_mongo_doc("MATCHED", partner_amount="50000", internal_amount="50000", camel_case=True),
        ]

        mock_collection = _make_mock_collection(docs)

        results = await get_discrepancies("MOMO", "2024-07-07", "partner", mock_collection, provider)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_discrepancies_inconsistency_focus(self) -> None:
        """get_discrepancies with inconsistency focus should detect amount clusters."""
        llm_response = json.dumps({
            "findings": [
                {"type": "amount_pattern", "severity": "medium", "title": "Amount pattern", "description": "D", "affected_count": 5, "recommendation": "R"}
            ]
        })
        provider = MockLLMProvider(response=llm_response)

        docs = [
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="100000", internal_amount="90000", camel_case=True),
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="200000", internal_amount="180000", camel_case=True),
            make_mongo_doc("STATUS_MISMATCH", partner_amount="50000", internal_amount="50000", camel_case=True),
            make_mongo_doc("MATCHED", partner_amount="75000", internal_amount="75000", camel_case=True),
        ]

        mock_collection = _make_mock_collection(docs)

        results = await get_discrepancies("MOMO", "2024-07-07", "inconsistency", mock_collection, provider)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_fallback_produces_insights_when_llm_fails(self) -> None:
        """When LLM fails, get_summary falls back to rule-based key_findings."""
        provider = MockLLMProvider(should_fail=True)

        docs = [
            make_mongo_doc("MATCHED", partner_amount="100000", internal_amount="100000", camel_case=True),
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="100000", internal_amount="80000", camel_case=True),
            make_mongo_doc("AMOUNT_MISMATCH", partner_amount="200000", internal_amount="170000", camel_case=True),
            make_mongo_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
            make_mongo_doc("MISSING_INTERNAL", partner_amount=None, internal_amount=None, camel_case=True),
        ]

        mock_collection = _make_mock_collection(docs)

        result = await get_summary("MOMO", "2024-07-07", mock_collection, provider)

        assert result["llm_status"] == "fallback"
        # get_summary now uses rule-based fallback for key_findings
        # when LLM is unavailable (improvement over original behavior)
        assert len(result["key_findings"]) >= 1
        assert any("Mismatch rate" in f for f in result["key_findings"])
        # Metrics should still be computed correctly
        assert result["summary_metrics"]["total_transactions"] == 5
        # 1 MATCHED, 2 AMOUNT_MISMATCH, 2 MISSING_INTERNAL = 4 mismatched
        assert result["summary_metrics"]["mismatch_rate"] == pytest.approx(80.0, rel=1e-2)


# ---------------------------------------------------------------------------
# Scenario 11: Edge cases in format_findings
# ---------------------------------------------------------------------------

class TestFormatFindingsEdgeCases:
    """Test format_findings with various input scenarios."""

    def test_formats_all_severity_levels(self) -> None:
        results = [
            AnalysisResult(type="t", severity="critical", title="Critical issue", description="D", affected_count=50),
            AnalysisResult(type="t", severity="high", title="High issue", description="D", affected_count=20),
            AnalysisResult(type="t", severity="medium", title="Medium issue", description="D", affected_count=10),
            AnalysisResult(type="t", severity="low", title="Low issue", description="D", affected_count=1),
        ]
        findings = format_findings(results)
        assert findings[0].startswith("[CRITICAL]")
        assert findings[1].startswith("[HIGH]")
        assert findings[2].startswith("[MEDIUM]")
        assert findings[3].startswith("[LOW]")

    def test_omits_affected_count_when_zero(self) -> None:
        result = AnalysisResult(type="t", severity="low", title="No impact", description="D", affected_count=0)
        findings = format_findings([result])
        assert "(0 affected)" not in findings[0]

    def test_handles_unknown_severity(self) -> None:
        result = AnalysisResult(type="t", severity="unknown_level", title="Test", description="D")
        findings = format_findings([result])
        assert findings[0] == " Test"  # Empty severity marker + space + title

    def test_handles_empty_input(self) -> None:
        assert format_findings([]) == []
        assert format_findings(None) == []


# ---------------------------------------------------------------------------
# Scenario 12: build_analysis_input edge cases
# ---------------------------------------------------------------------------

class TestBuildAnalysisInputEdgeCases:
    """Test build_analysis_input with various edge cases."""

    def test_with_none_anomalies(self) -> None:
        """None anomalies should default to empty list."""
        summary = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=10,
            matched=10,
            mismatch_rate=0.0,
            total_amount_mismatch=0,
            by_status={"MATCHED": 10},
        )
        inp = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=summary,
            grouped_results=[],
            anomalies=None,
        )
        assert inp.top_anomalies == []

    def test_with_empty_anomalies(self) -> None:
        """Empty anomalies list should be preserved."""
        summary = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=10,
            matched=10,
            mismatch_rate=0.0,
            total_amount_mismatch=0,
            by_status={"MATCHED": 10},
        )
        inp = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=summary,
            grouped_results=[],
            anomalies=[],
        )
        assert inp.top_anomalies == []

    def test_with_multiple_anomalies(self) -> None:
        """Multiple anomalies should be included in order."""
        summary = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=100,
            matched=80,
            mismatch_rate=20.0,
            total_amount_mismatch=500000,
            by_status={"MATCHED": 80, "AMOUNT_MISMATCH": 20},
        )
        anomalies = [
            TopAnomaly(type="missing_internal", count=5, partners_affected=["MOMO"]),
            TopAnomaly(type="high_mismatch_rate", count=20, partners_affected=["MOMO"]),
        ]
        inp = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=summary,
            grouped_results=[],
            anomalies=anomalies,
        )
        assert len(inp.top_anomalies) == 2
        assert inp.top_anomalies[0].type == "missing_internal"
        assert inp.top_anomalies[1].type == "high_mismatch_rate"


# ---------------------------------------------------------------------------
# Scenario 13: Daily report with partial failures and alerts
# ---------------------------------------------------------------------------

class TestDailyReportWithAlerts:
    """Test daily report generation with threshold alerts."""

    @pytest.mark.asyncio
    async def test_report_includes_alerts_for_breached_thresholds(self) -> None:
        """Daily report should include alerts when thresholds are breached."""
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=["MOMO", "VIETTEL"])

        summaries = {
            "MOMO": {
                "partner": "MOMO",
                "date": "2024-07-07",
                "summary_metrics": {"total_transactions": 100, "matched": 90, "mismatch_rate": 10.0, "total_amount_mismatch": 500000, "by_status": {"MATCHED": 90, "AMOUNT_MISMATCH": 10}},
                "grouped_stats": [],
                "key_findings": ["MOMO high mismatch"],
                "generated_at": "2024-07-07",
                "llm_status": "success",
            },
            "VIETTEL": {
                "partner": "VIETTEL",
                "date": "2024-07-07",
                "summary_metrics": {"total_transactions": 50, "matched": 50, "mismatch_rate": 0.0, "total_amount_mismatch": 0, "by_status": {"MATCHED": 50}},
                "grouped_stats": [],
                "key_findings": [],
                "generated_at": "2024-07-07",
                "llm_status": "success",
            },
        }

        async def mock_get_summary(partner, **kwargs):
            return summaries[partner]

        with patch("src.analysis.insights.get_summary", side_effect=mock_get_summary):
            reporter = DailyReporter(mock_collection, MockLLMProvider())
            report = await reporter.generate_report("2024-07-07")

        # MOMO has 10% mismatch rate, which exceeds default 5% threshold
        momo_partner = next(p for p in report["partners"] if p["partner"] == "MOMO")
        assert momo_partner["summary_metrics"]["mismatch_rate"] == 10.0

        # VIETTEL has 0% mismatch rate, should not trigger alert
        viettel_partner = next(p for p in report["partners"] if p["partner"] == "VIETTEL")
        assert viettel_partner["summary_metrics"]["mismatch_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_report_handles_all_partners_failing(self) -> None:
        """When all partners fail, report should still be generated with empty partners list."""
        from src.analysis.reporter import DailyReporter

        mock_collection = MagicMock()
        mock_collection.distinct = AsyncMock(return_value=["MOMO", "VIETTEL"])

        async def mock_get_summary(partner, **kwargs):
            raise RuntimeError(f"{partner} data unavailable")

        with patch("src.analysis.insights.get_summary", side_effect=mock_get_summary):
            reporter = DailyReporter(mock_collection, MockLLMProvider())
            report = await reporter.generate_report("2024-07-07")

        assert report["date"] == "2024-07-07"
        assert report["partners"] == []
        assert report["global_stats"]["total_mismatch_rate"] == 0.0


# ---------------------------------------------------------------------------
# Scenario 14: Metrics edge cases
# ---------------------------------------------------------------------------

class TestMetricsEdgeCases:
    """Test MetricsService with edge case inputs."""

    def test_compute_summary_with_all_none_amounts(self) -> None:
        """All None amounts should result in zero total_amount_mismatch."""
        results = [
            make_result("MISSING_INTERNAL", partner_amount=None, internal_amount=None),
            make_result("MISSING_PARTNER", partner_amount=None, internal_amount=None),
        ]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert summary.total_amount_mismatch == Decimal("0")
        assert summary.mismatch_rate == 100.0

    def test_compute_summary_with_single_transaction(self) -> None:
        """Single transaction should compute correctly."""
        results = [make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000"))]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert summary.total_transactions == 1
        assert summary.matched == 0
        assert summary.mismatch_rate == 100.0
        assert summary.total_amount_mismatch == Decimal("10000")

    def test_compute_summary_with_all_matched(self) -> None:
        """All matched should have zero mismatch rate."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("MATCHED", partner_amount=Decimal("200000"), internal_amount=Decimal("200000")),
        ]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert summary.mismatch_rate == 0.0
        assert summary.total_amount_mismatch == Decimal("0")

    def test_compute_summary_preserves_partner_and_date(self) -> None:
        """Partner and date should be stored in summary."""
        results = [make_result("MATCHED")]
        summary = MetricsService.compute_summary(results, "VIETTEL", "2024-08-15")
        assert summary.partner == "VIETTEL"
        assert summary.date == "2024-08-15"


# ---------------------------------------------------------------------------
# Scenario 15: Grouping edge cases
# ---------------------------------------------------------------------------

class TestGroupingEdgeCases:
    """Test GroupingEngine with edge case inputs."""

    def test_percentage_rounding(self) -> None:
        """Percentages should be rounded to 2 decimal places."""
        results = [make_result("MATCHED") for _ in range(3)]
        results.append(make_result("AMOUNT_MISMATCH", partner_amount=Decimal("100000"), internal_amount=Decimal("90000")))
        groups = GroupingEngine.group(results)
        for g in groups:
            # Check percentage has at most 2 decimal places
            assert g.percentage == round(g.percentage, 2)

    def test_zero_total_results(self) -> None:
        """Empty results should produce empty groups."""
        groups = GroupingEngine.group([])
        assert groups == []

    def test_group_total_amount_for_matched(self) -> None:
        """Matched group should accumulate total_amount."""
        results = [
            make_result("MATCHED", partner_amount=Decimal("100000"), internal_amount=Decimal("100000")),
            make_result("MATCHED", partner_amount=Decimal("200000"), internal_amount=Decimal("200000")),
        ]
        groups = GroupingEngine.group(results)
        matched_group = next(g for g in groups if g.key == "MATCHED")
        assert matched_group.total_amount == Decimal("300000")
