"""Tests for AI Analysis Layer services (helpers)."""

import json
from decimal import Decimal
from unittest.mock import MagicMock


from src.analysis.schemas import (
    AnalysisResult,
    GroupResult,
    SummaryResult,
    TopAnomaly,
)
from src.analysis.services import (
    build_analysis_input,
    format_findings,
    parse_llm_insights,
    rule_based_pre_process,
)


class TestBuildAnalysisInput:
    """Test build_analysis_input helper."""

    def test_builds_valid_input(self) -> None:
        metrics = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=1500,
            matched=1450,
            mismatch_rate=3.33,
            total_amount_mismatch=25_000_000,
            by_status={"MATCHED": 1450, "AMOUNT_MISMATCH": 30},
        )
        groups = [
            GroupResult(
                key="AMOUNT_MISMATCH",
                count=30,
                percentage=2.0,
                total_amount=25_000_000,
                details={"avg_difference": 833333},
            )
        ]

        result = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=metrics,
            grouped_results=groups,
        )

        assert result.partner == "MOMO"
        assert result.date == "2024-07-07"
        assert result.focus == "operational"
        assert result.summary_metrics["total_transactions"] == 1500
        assert len(result.grouped_stats) == 1
        assert result.grouped_stats[0]["key"] == "AMOUNT_MISMATCH"

    def test_empty_anomalies_when_not_provided(self) -> None:
        metrics = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=100,
            matched=100,
            mismatch_rate=0.0,
            by_status={"MATCHED": 100},
        )
        result = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=metrics,
            grouped_results=[],
        )
        assert result.top_anomalies == []

    def test_includes_anomalies_when_provided(self) -> None:
        metrics = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=100,
            matched=100,
            mismatch_rate=0.0,
            by_status={"MATCHED": 100},
        )
        anomalies = [
            TopAnomaly(type="missing_internal", count=5, partners_affected=["MOMO"])
        ]
        result = build_analysis_input(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            metrics_result=metrics,
            grouped_results=[],
            anomalies=anomalies,
        )
        assert len(result.top_anomalies) == 1
        assert result.top_anomalies[0].type == "missing_internal"


class TestParseLlmInsights:
    """Test parse_llm_insights helper."""

    def test_parses_valid_json(self) -> None:
        response = json.dumps({
            "findings": [
                {
                    "type": "operational_delay",
                    "severity": "medium",
                    "title": "Delay detected",
                    "description": "Some transactions delayed",
                    "affected_count": 5,
                    "recommendation": "Check pipeline",
                }
            ]
        })
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "operational_delay"
        assert results[0].severity == "medium"
        assert results[0].affected_count == 5

    def test_parses_multiple_findings(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "t1", "severity": "low", "title": "T1", "description": "D1", "affected_count": 1, "recommendation": "R1"},
                {"type": "t2", "severity": "high", "title": "T2", "description": "D2", "affected_count": 2, "recommendation": "R2"},
            ]
        })
        results = parse_llm_insights(response)
        assert len(results) == 2

    def test_handles_markdown_code_block(self) -> None:
        response = '```json\n{"findings": [{"type": "test", "severity": "low", "title": "T", "description": "D", "affected_count": 0, "recommendation": ""}]}\n```'
        results = parse_llm_insights(response)
        assert len(results) == 1
        assert results[0].type == "test"

    def test_handles_json_with_surrounding_text(self) -> None:
        response = "Here is the analysis:\n\n{\"findings\": [{\"type\": \"test\", \"severity\": \"low\", \"title\": \"T\", \"description\": \"D\", \"affected_count\": 0, \"recommendation\": \"\"}]}\n\nHope this helps!"
        results = parse_llm_insights(response)
        assert len(results) == 1

    def test_returns_empty_list_on_invalid_json(self) -> None:
        results = parse_llm_insights("not json at all")
        assert results == []

    def test_returns_empty_list_on_missing_findings(self) -> None:
        response = json.dumps({"other_key": "value"})
        results = parse_llm_insights(response)
        assert results == []

    def test_returns_empty_list_on_non_list_findings(self) -> None:
        response = json.dumps({"findings": "not a list"})
        results = parse_llm_insights(response)
        assert results == []

    def test_skips_invalid_finding_entries(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "valid", "severity": "low", "title": "V", "description": "D", "affected_count": 0, "recommendation": ""},
                {"type": 123, "severity": "low", "title": "V", "description": "D", "affected_count": 0, "recommendation": ""},  # type is int, still str-able
            ]
        })
        results = parse_llm_insights(response)
        # Both should parse since str(123) works
        assert len(results) == 2

    def test_defaults_for_missing_fields(self) -> None:
        response = json.dumps({
            "findings": [
                {"type": "test", "severity": "low", "title": "T", "description": "D"}
            ]
        })
        results = parse_llm_insights(response)
        assert results[0].affected_count == 0
        assert results[0].recommendation == ""


class TestFormatFindings:
    """Test format_findings helper."""

    def test_formats_single_finding(self) -> None:
        results = [
            AnalysisResult(
                type="operational_delay",
                severity="medium",
                title="Delay detected",
                description="Some delay",
                affected_count=5,
                recommendation="Check pipeline",
            )
        ]
        formatted = format_findings(results)
        assert len(formatted) == 1
        assert "[MEDIUM]" in formatted[0]
        assert "Delay detected" in formatted[0]
        assert "5 affected" in formatted[0]

    def test_formats_multiple_findings(self) -> None:
        results = [
            AnalysisResult(type="t1", severity="critical", title="Critical issue", description="D", affected_count=10),
            AnalysisResult(type="t2", severity="low", title="Minor issue", description="D", affected_count=1),
        ]
        formatted = format_findings(results)
        assert len(formatted) == 2
        assert "[CRITICAL]" in formatted[0]
        assert "[LOW]" in formatted[1]

    def test_omits_affected_count_when_zero(self) -> None:
        results = [
            AnalysisResult(type="t", severity="low", title="No count", description="D", affected_count=0)
        ]
        formatted = format_findings(results)
        assert "affected" not in formatted[0]

    def test_returns_empty_for_empty_input(self) -> None:
        assert format_findings([]) == []

    def test_handles_unknown_severity(self) -> None:
        results = [
            AnalysisResult(type="t", severity="unknown_level", title="Test", description="D")
        ]
        formatted = format_findings(results)
        assert "Test" in formatted[0]


class TestRuleBasedPreProcess:
    """Test rule-based pre-processing helpers."""

    def _make_result(self, status: str, partner: str = "MOMO") -> MagicMock:
        """Create a mock reconciliation result."""
        r = MagicMock()
        r.reconciliation_status.value = status
        r.partner = partner
        r.partner_amount = None
        r.internal_amount = None
        return r

    def test_operational_extracts_missing_internal(self) -> None:
        results = [
            self._make_result("MATCHED"),
            self._make_result("MISSING_INTERNAL"),
            self._make_result("MISSING_INTERNAL"),
        ]
        anomalies = rule_based_pre_process(results, "operational")
        assert len(anomalies) == 1
        assert anomalies[0].type == "missing_internal"
        assert anomalies[0].count == 2

    def test_operational_extracts_missing_partner(self) -> None:
        results = [
            self._make_result("MISSING_PARTNER"),
            self._make_result("MISSING_PARTNER"),
            self._make_result("MISSING_PARTNER"),
        ]
        anomalies = rule_based_pre_process(results, "operational")
        assert len(anomalies) == 1
        assert anomalies[0].type == "missing_partner"
        assert anomalies[0].count == 3

    def test_operational_extracts_both_types(self) -> None:
        results = [
            self._make_result("MISSING_INTERNAL"),
            self._make_result("MISSING_PARTNER"),
        ]
        anomalies = rule_based_pre_process(results, "operational")
        assert len(anomalies) == 2
        types = {a.type for a in anomalies}
        assert "missing_internal" in types
        assert "missing_partner" in types

    def test_partner_high_mismatch_rate(self) -> None:
        results = [self._make_result("MATCHED")]
        summary = {"mismatch_rate": 10.0, "total_transactions": 1000, "partner": "MOMO"}
        anomalies = rule_based_pre_process(results, "partner", summary)
        assert len(anomalies) == 1
        assert anomalies[0].type == "high_mismatch_rate"

    def test_partner_no_anomaly_when_rate_low(self) -> None:
        results = [self._make_result("MATCHED")]
        summary = {"mismatch_rate": 2.0, "total_transactions": 1000, "partner": "MOMO"}
        anomalies = rule_based_pre_process(results, "partner", summary)
        assert anomalies == []

    def test_inconsistency_amount_mismatch(self) -> None:
        r = MagicMock()
        r.reconciliation_status.value = "AMOUNT_MISMATCH"
        r.partner_amount = Decimal("100000")
        r.internal_amount = Decimal("110000")
        anomalies = rule_based_pre_process([r], "inconsistency")
        assert len(anomalies) == 1
        assert anomalies[0].type == "amount_mismatch_cluster"

    def test_inconsistency_status_mismatch(self) -> None:
        results = [self._make_result("STATUS_MISMATCH")]
        anomalies = rule_based_pre_process(results, "inconsistency")
        assert len(anomalies) == 1
        assert anomalies[0].type == "status_mismatch_cluster"

    def test_unknown_focus_returns_empty(self) -> None:
        results = [self._make_result("MATCHED")]
        anomalies = rule_based_pre_process(results, "unknown_focus")
        assert anomalies == []
