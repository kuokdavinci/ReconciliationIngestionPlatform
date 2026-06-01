"""Tests for AI Analysis Layer schemas."""

import pytest
from pydantic import ValidationError

from src.analysis.schemas import (
    AnalysisInput,
    AnalysisResult,
    GroupCriteria,
    GroupResult,
    SummaryResult,
    TopAnomaly,
)


class TestGroupCriteria:
    """Test GroupCriteria schema."""

    def test_default_values(self) -> None:
        criteria = GroupCriteria()
        assert criteria.status is None
        assert criteria.partner is None
        assert criteria.amount_range_min is None
        assert criteria.amount_range_max is None
        assert criteria.date_from is None
        assert criteria.date_to is None

    def test_all_fields_set(self) -> None:
        from datetime import date

        criteria = GroupCriteria(
            status="MATCHED",
            partner="MOMO",
            amount_range_min=100_000,
            amount_range_max=1_000_000,
            date_from=date(2024, 7, 1),
            date_to=date(2024, 7, 7),
        )
        assert criteria.status == "MATCHED"
        assert criteria.partner == "MOMO"
        assert criteria.amount_range_min == 100_000
        assert criteria.amount_range_max == 1_000_000


class TestGroupResult:
    """Test GroupResult schema."""

    def test_minimal(self) -> None:
        result = GroupResult(key="MATCHED", count=100, percentage=80.0)
        assert result.key == "MATCHED"
        assert result.count == 100
        assert result.percentage == 80.0
        assert result.total_amount == 0.0
        assert result.details == {}

    def test_with_details(self) -> None:
        result = GroupResult(
            key="AMOUNT_MISMATCH",
            count=30,
            percentage=2.0,
            total_amount=25_000_000,
            details={"avg_difference": 833333, "min_difference": 1000, "max_difference": 5_000_000},
        )
        assert result.details["avg_difference"] == 833333


class TestSummaryResult:
    """Test SummaryResult schema."""

    def test_minimal(self) -> None:
        result = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=1500,
            matched=1450,
            mismatch_rate=3.33,
        )
        assert result.partner == "MOMO"
        assert result.total_amount_mismatch == 0.0
        assert result.by_status == {}

    def test_full(self) -> None:
        result = SummaryResult(
            partner="MOMO",
            date="2024-07-07",
            total_transactions=1500,
            matched=1450,
            mismatch_rate=3.33,
            total_amount_mismatch=25_000_000,
            by_status={
                "MATCHED": 1450,
                "AMOUNT_MISMATCH": 30,
                "STATUS_MISMATCH": 10,
                "MISSING_INTERNAL": 5,
                "MISSING_PARTNER": 5,
            },
        )
        assert result.by_status["AMOUNT_MISMATCH"] == 30


class TestAnalysisResult:
    """Test AnalysisResult schema."""

    def test_minimal(self) -> None:
        result = AnalysisResult(
            type="operational_delay",
            severity="medium",
            title="Delay detected",
            description="Some transactions are delayed",
        )
        assert result.affected_count == 0
        assert result.recommendation == ""

    def test_full(self) -> None:
        result = AnalysisResult(
            type="operational_delay",
            severity="medium",
            title="Phát hiện chậm đối soát",
            description="5 giao dịch MISSING_INTERNAL cho thấy internal system chưa nhận được dữ liệu kịp thời.",
            affected_count=5,
            recommendation="Kiểm tra pipeline ingestion cho MOMO ngày 2024-07-07",
        )
        assert result.affected_count == 5
        assert "pipeline" in result.recommendation


class TestTopAnomaly:
    """Test TopAnomaly schema."""

    def test_minimal(self) -> None:
        anomaly = TopAnomaly(type="missing_internal_batch", count=5)
        assert anomaly.partners_affected == []
        assert anomaly.amount_range == ""

    def test_full(self) -> None:
        anomaly = TopAnomaly(
            type="missing_internal_batch",
            count=5,
            partners_affected=["MOMO"],
            amount_range="0-100k",
        )
        assert anomaly.partners_affected == ["MOMO"]


class TestAnalysisInput:
    """Test AnalysisInput schema — the LLM input contract."""

    def test_minimal(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            summary_metrics={"total_transactions": 1500, "matched": 1450},
            grouped_stats=[],
        )
        assert inp.focus == "operational"
        assert inp.top_anomalies == []

    def test_full(self) -> None:
        inp = AnalysisInput(
            partner="MOMO",
            date="2024-07-07",
            focus="operational",
            summary_metrics={
                "total_transactions": 1500,
                "matched": 1450,
                "mismatch_rate": 3.33,
            },
            grouped_stats=[
                {
                    "key": "AMOUNT_MISMATCH",
                    "count": 30,
                    "percentage": 2.0,
                    "total_amount": 25_000_000,
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
        assert inp.focus == "operational"
        assert len(inp.grouped_stats) == 1
        assert len(inp.top_anomalies) == 1

    def test_no_raw_data_contract(self) -> None:
        """Verify AnalysisInput does not have fields for raw transaction data."""
        fields = set(AnalysisInput.model_fields.keys())
        # Should NOT contain raw transaction identifiers
        assert "partner_txn_id" not in fields
        assert "internal_txn_id" not in fields
        assert "raw_transactions" not in fields
