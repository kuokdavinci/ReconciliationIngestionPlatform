"""Tests for AI insight guardrail validation."""

from decimal import Decimal

import pytest

from src.analysis.guardrails import validate_insights
from src.analysis.schemas import AnalysisInput, AnalysisResult, GroupResult, SummaryResult, TopAnomaly


def _make_input(
    mismatch_rate: float = 5.0,
    total_transactions: int = 100,
    matched: int = 95,
    focus: str = "operational",
    anomalies: list[TopAnomaly] | None = None,
) -> AnalysisInput:
    return AnalysisInput(
        partner="MOMO",
        date="2024-07-07",
        focus=focus,
        summary_metrics={
            "total_transactions": total_transactions,
            "matched": matched,
            "mismatch_rate": mismatch_rate,
            "total_amount_mismatch": 500000.0,
            "by_status": {"MATCHED": matched, "MISSING_INTERNAL": total_transactions - matched},
        },
        grouped_stats=[
            {"key": "MATCHED", "count": matched, "percentage": 95.0, "total_amount": 1000000.0},
        ],
        top_anomalies=anomalies or [],
    )


def _make_insight(
    type: str = "operational_delay",
    severity: str = "medium",
    title: str = "Test insight",
    description: str = "A test insight for validation",
    affected_count: int = 5,
) -> AnalysisResult:
    return AnalysisResult(
        type=type,
        severity=severity,
        title=title,
        description=description,
        affected_count=affected_count,
        recommendation="Investigate and resolve",
    )


class TestValidClaims:
    """Guardrails should pass valid, well-formed insights."""

    def test_perfectly_valid_insight(self) -> None:
        input_data = _make_input(mismatch_rate=5.0, total_transactions=100)
        insights = [_make_insight(severity="medium", affected_count=5)]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert result.risk_level == "none"

    def test_low_mismatch_low_severity(self) -> None:
        input_data = _make_input(mismatch_rate=0.5, total_transactions=100)
        insights = [_make_insight(severity="low", affected_count=2)]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert result.risk_level == "none"


class TestUnsupportedClaims:
    """Guardrails should flag unsupported or exaggerated claims."""

    def test_critical_severity_with_low_mismatch(self) -> None:
        input_data = _make_input(mismatch_rate=0.5, total_transactions=100)
        insights = [_make_insight(severity="critical", affected_count=2)]
        result = validate_insights(input_data, insights)
        assert not result.is_valid
        assert result.risk_level == "high"

    def test_affected_count_exceeds_total(self) -> None:
        input_data = _make_input(total_transactions=100)
        insights = [_make_insight(severity="medium", affected_count=500)]
        result = validate_insights(input_data, insights)
        assert not result.is_valid
        assert len(result.unsupported_claims) == 1
        assert "affected_count" in result.unsupported_claims[0].field

    def test_empty_title(self) -> None:
        input_data = _make_input()
        insights = [_make_insight(title="   ", description="Some description")]
        result = validate_insights(input_data, insights)
        assert not result.is_valid


class TestPartiallySupportedClaims:
    """Guardrails should differentiate between medium and high risk."""

    def test_high_severity_with_very_low_mismatch(self) -> None:
        input_data = _make_input(mismatch_rate=0.3, total_transactions=200)
        insights = [_make_insight(severity="high", affected_count=1)]
        result = validate_insights(input_data, insights)
        assert not result.is_valid
        assert result.risk_level == "high"

    def test_slightly_elevated_severity_gives_low_warning(self) -> None:
        input_data = _make_input(mismatch_rate=3.0, total_transactions=100)
        insights = [_make_insight(severity="high", affected_count=2)]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert result.risk_level == "low"

    def test_multiple_issues_aggregate_risk(self) -> None:
        input_data = _make_input(mismatch_rate=0.5, total_transactions=50)
        insights = [
            _make_insight(severity="critical", affected_count=200),
            _make_insight(severity="medium", affected_count=1),
        ]
        result = validate_insights(input_data, insights)
        assert not result.is_valid
        assert result.risk_level == "high"
        assert len(result.findings) >= 2


class TestFocusConsistency:
    """Guardrails should enforce focus-type consistency."""

    def test_partner_claim_under_operational_focus(self) -> None:
        input_data = _make_input(focus="operational")
        insights = [_make_insight(type="partner_pattern", severity="medium")]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert len(result.warnings) >= 1
        assert any("partner" in w.message for w in result.warnings)

    def test_operational_claim_under_partner_focus(self) -> None:
        input_data = _make_input(focus="partner")
        insights = [_make_insight(type="batch_failure", severity="medium")]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert len(result.warnings) >= 1


class TestAnomalyConsistency:
    """Guardrails should cross-reference LLM claims against TopAnomaly values."""

    def test_overstated_anomaly_count_detected(self) -> None:
        anomaly = TopAnomaly(type="missing_internal", count=10, partners_affected=["MOMO"])
        input_data = _make_input(anomalies=[anomaly])
        insights = [_make_insight(type="missing_internal", affected_count=100)]
        result = validate_insights(input_data, insights)
        assert not result.is_valid
        assert result.risk_level == "high"

    def test_slightly_overstated_gives_low_warning(self) -> None:
        anomaly = TopAnomaly(type="missing_internal", count=10, partners_affected=["MOMO"])
        input_data = _make_input(anomalies=[anomaly])
        insights = [_make_insight(type="missing_internal", affected_count=18)]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert result.risk_level == "low"

    def test_no_warning_when_claim_matches_data(self) -> None:
        anomaly = TopAnomaly(type="missing_internal", count=10, partners_affected=["MOMO"])
        input_data = _make_input(anomalies=[anomaly])
        insights = [_make_insight(type="missing_internal", affected_count=10)]
        result = validate_insights(input_data, insights)
        assert result.is_valid
        assert result.risk_level == "none"

    def test_empty_insights_returns_valid(self) -> None:
        input_data = _make_input()
        result = validate_insights(input_data, [])
        assert result.is_valid
        assert result.risk_level == "none"
