"""Tests for AI Analysis Layer prompt templates."""


from src.analysis.prompts import (
    build_analysis_prompt,
    build_system_prompt,
    _format_metrics_section,
    _format_grouped_stats_section,
    _format_anomalies_section,
)
from src.analysis.schemas import AnalysisInput, TopAnomaly


class TestBuildSystemPrompt:
    """Test build_system_prompt function."""

    def test_returns_non_empty_string(self) -> None:
        prompt = build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_role_definition(self) -> None:
        prompt = build_system_prompt()
        assert "AI analysis assistant" in prompt
        assert "reconciliation operations" in prompt

    def test_contains_constraints(self) -> None:
        prompt = build_system_prompt()
        assert "ONLY discuss the data provided" in prompt
        assert "NOT perform fraud detection" in prompt
        assert "MUST be valid JSON" in prompt

    def test_contains_output_format(self) -> None:
        prompt = build_system_prompt()
        assert '"findings"' in prompt
        assert '"type"' in prompt
        assert '"severity"' in prompt

    def test_contains_focus_types(self) -> None:
        prompt = build_system_prompt()
        assert "operational" in prompt
        assert "partner" in prompt
        assert "inconsistency" in prompt

    def test_idempotent(self) -> None:
        """Same call returns identical output."""
        prompt1 = build_system_prompt()
        prompt2 = build_system_prompt()
        assert prompt1 == prompt2


class TestBuildAnalysisPrompt:
    """Test build_analysis_prompt function."""

    def _make_input(self, focus: str = "operational") -> AnalysisInput:
        return AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus=focus,
            summary_metrics={
                "total_transactions": 1500,
                "matched": 1450,
                "mismatch_rate": 3.33,
                "total_amount_mismatch": 25_000_000,
                "by_status": {
                    "MATCHED": 1450,
                    "AMOUNT_MISMATCH": 30,
                    "STATUS_MISMATCH": 10,
                    "MISSING_INTERNAL": 5,
                    "MISSING_PARTNER": 5,
                },
            },
            grouped_stats=[
                {
                    "key": "AMOUNT_MISMATCH",
                    "count": 30,
                    "percentage": 2.0,
                    "total_amount": 25_000_000,
                    "details": {"avg_difference": 833333},
                }
            ],
            top_anomalies=[
                TopAnomaly(
                    type="missing_internal_batch",
                    count=5,
                    partners_affected=["MOMO"],
                    amount_range="0-100k",
                )
            ],
        )

    def test_contains_partner_and_date(self) -> None:
        inp = self._make_input()
        prompt = build_analysis_prompt(inp)
        assert "**Partner:** MOMO" in prompt
        assert "**Date:** 2024-07-07" in prompt

    def test_contains_focus_instruction_operational(self) -> None:
        inp = self._make_input(focus="operational")
        prompt = build_analysis_prompt(inp)
        assert "MISSING_INTERNAL" in prompt
        assert "MISSING_PARTNER" in prompt

    def test_contains_focus_instruction_partner(self) -> None:
        inp = self._make_input(focus="partner")
        prompt = build_analysis_prompt(inp)
        assert "partner behavior" in prompt.lower() or "partner" in prompt.lower()

    def test_contains_focus_instruction_inconsistency(self) -> None:
        inp = self._make_input(focus="inconsistency")
        prompt = build_analysis_prompt(inp)
        assert "AMOUNT_MISMATCH" in prompt
        assert "STATUS_MISMATCH" in prompt

    def test_contains_metrics_section(self) -> None:
        inp = self._make_input()
        prompt = build_analysis_prompt(inp)
        assert "## Summary Metrics" in prompt
        assert "Total Transactions: 1500" in prompt
        assert "Mismatch Rate: 3.33%" in prompt

    def test_contains_grouped_stats_section(self) -> None:
        inp = self._make_input()
        prompt = build_analysis_prompt(inp)
        assert "## Grouped Stats" in prompt
        assert "AMOUNT_MISMATCH" in prompt

    def test_contains_anomalies_section(self) -> None:
        inp = self._make_input()
        prompt = build_analysis_prompt(inp)
        assert "## Top Anomalies" in prompt
        assert "missing_internal_batch" in prompt

    def test_no_raw_data_exposure(self) -> None:
        """Verify prompt does not contain raw transaction identifiers."""
        inp = self._make_input()
        prompt = build_analysis_prompt(inp)
        assert "partner_txn_id" not in prompt
        assert "internal_txn_id" not in prompt

    def test_default_focus_when_not_specified(self) -> None:
        """When focus is not set, defaults to operational."""
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            summary_metrics={"total_transactions": 100, "matched": 100},
            grouped_stats=[],
        )
        prompt = build_analysis_prompt(inp)
        assert "**Focus:** operational" in prompt

    def test_idempotent(self) -> None:
        """Same input produces identical prompt."""
        inp = self._make_input()
        prompt1 = build_analysis_prompt(inp)
        prompt2 = build_analysis_prompt(inp)
        assert prompt1 == prompt2


class TestFormatHelpers:
    """Test internal formatting helper functions."""

    def test_format_metrics_empty(self) -> None:
        result = _format_metrics_section({})
        assert "## Summary Metrics" in result
        assert "Total Transactions: N/A" in result

    def test_format_metrics_with_by_status(self) -> None:
        result = _format_metrics_section(
            {
                "total_transactions": 100,
                "matched": 90,
                "mismatch_rate": 10.0,
                "by_status": {"MATCHED": 90, "AMOUNT_MISMATCH": 10},
            }
        )
        assert "MATCHED: 90" in result
        assert "AMOUNT_MISMATCH: 10" in result

    def test_format_grouped_stats_empty(self) -> None:
        result = _format_grouped_stats_section([])
        assert "## Grouped Stats" in result
        assert "No grouped statistics available" in result

    def test_format_grouped_stats_with_details(self) -> None:
        result = _format_grouped_stats_section(
            [
                {
                    "key": "MISSING_INTERNAL",
                    "count": 5,
                    "percentage": 0.33,
                    "total_amount": 0,
                    "details": {"avg_difference": 0},
                }
            ]
        )
        assert "MISSING_INTERNAL" in result
        assert "avg_difference" in result

    def test_format_anomalies_empty(self) -> None:
        result = _format_anomalies_section([])
        assert "## Top Anomalies" in result
        assert "No anomalies detected" in result

    def test_format_anomalies_with_data(self) -> None:
        result = _format_anomalies_section(
            [
                {
                    "type": "missing_internal_batch",
                    "count": 5,
                    "partners_affected": ["MOMO", "VNPAY"],
                    "amount_range": "0-100k",
                }
            ]
        )
        assert "missing_internal_batch" in result
        assert "MOMO" in result
        assert "VNPAY" in result
