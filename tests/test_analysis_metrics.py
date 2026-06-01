"""Tests for MetricsService — single source of truth for reconciliation statistics."""

from decimal import Decimal

import pytest

from src.analysis.grouping import GroupingEngine
from src.analysis.metrics import MetricsService
from src.analysis.schemas import GroupResult, SummaryResult
from src.core.enums import ReconciliationStatus


class _FakeResult:
    """Minimal fake reconciliation result for testing."""

    def __init__(
        self,
        status: ReconciliationStatus,
        partner_amount: Decimal | None = None,
        internal_amount: Decimal | None = None,
        partner: str = "MOMO",
    ) -> None:
        self.reconciliation_status = status
        self.partner_amount = partner_amount
        self.internal_amount = internal_amount
        self.partner = partner


class TestComputeSummary:
    """Test compute_summary method."""

    def test_empty_results(self) -> None:
        result = MetricsService.compute_summary([], "MOMO", "2024-07-07")
        assert result.total_transactions == 0
        assert result.matched == 0
        assert result.mismatch_rate == 0.0

    def test_all_matched(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000"))
            for _ in range(10)
        ]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert summary.total_transactions == 10
        assert summary.matched == 10
        assert summary.mismatch_rate == 0.0
        assert summary.by_status == {"MATCHED": 10}

    def test_mismatch_rate_calculation(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH),
        ]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert summary.total_transactions == 4
        assert summary.matched == 3
        assert summary.mismatch_rate == 25.0

    def test_total_amount_mismatch(self) -> None:
        results = [
            _FakeResult(
                ReconciliationStatus.AMOUNT_MISMATCH,
                Decimal("100000"),
                Decimal("90000"),
            ),
            _FakeResult(
                ReconciliationStatus.AMOUNT_MISMATCH,
                Decimal("200000"),
                Decimal("180000"),
            ),
        ]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        # |100000-90000| + |200000-180000| = 10000 + 20000 = 30000
        assert summary.total_amount_mismatch == 30000.0

    def test_by_status_counts(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH),
            _FakeResult(ReconciliationStatus.STATUS_MISMATCH),
            _FakeResult(ReconciliationStatus.MISSING_INTERNAL),
        ]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert summary.by_status == {
            "MATCHED": 2,
            "AMOUNT_MISMATCH": 1,
            "STATUS_MISMATCH": 1,
            "MISSING_INTERNAL": 1,
        }

    def test_partner_and_date_stored(self) -> None:
        results = [_FakeResult(ReconciliationStatus.MATCHED)]
        summary = MetricsService.compute_summary(results, "VNPAY", "2024-08-01")
        assert summary.partner == "VNPAY"
        assert summary.date == "2024-08-01"


class TestSummaryFromGroups:
    """Test summary_from_groups cross-group statistics."""

    def test_empty_groups(self) -> None:
        result = MetricsService.summary_from_groups([], [])
        assert result["total_groups"] == 0
        assert result["largest_group"] is None
        assert result["largest_group_count"] == 0

    def test_largest_group_identified(self) -> None:
        groups = [
            GroupResult(key="MATCHED", count=100, percentage=80.0),
            GroupResult(key="AMOUNT_MISMATCH", count=20, percentage=16.0),
            GroupResult(key="STATUS_MISMATCH", count=5, percentage=4.0),
        ]
        result = MetricsService.summary_from_groups(groups, [])
        assert result["largest_group"] == "MATCHED"
        assert result["largest_group_count"] == 100
        assert result["total_groups"] == 3

    def test_mismatch_amount_sum(self) -> None:
        groups = [
            GroupResult(key="MATCHED", count=100, percentage=80.0, total_amount=500000),
            GroupResult(key="AMOUNT_MISMATCH", count=20, percentage=16.0, total_amount=25000),
            GroupResult(key="STATUS_MISMATCH", count=5, percentage=4.0, total_amount=5000),
        ]
        result = MetricsService.summary_from_groups(groups, [])
        # Only mismatch groups contribute
        assert result["total_mismatch_amount"] == 30000.0


class TestComputeMismatchRate:
    """Test standalone mismatch rate computation."""

    def test_empty(self) -> None:
        assert MetricsService.compute_mismatch_rate([]) == 0.0

    def test_all_matched(self) -> None:
        results = [_FakeResult(ReconciliationStatus.MATCHED) for _ in range(5)]
        assert MetricsService.compute_mismatch_rate(results) == 0.0

    def test_half_matched(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH),
        ]
        assert MetricsService.compute_mismatch_rate(results) == 50.0


class TestComputeAvgMismatchAmount:
    """Test average mismatch amount computation."""

    def test_no_mismatches(self) -> None:
        results = [_FakeResult(ReconciliationStatus.MATCHED, Decimal("100000"))]
        assert MetricsService.compute_avg_mismatch_amount(results) == 0.0

    def test_single_mismatch(self) -> None:
        results = [
            _FakeResult(
                ReconciliationStatus.AMOUNT_MISMATCH,
                Decimal("100000"),
                Decimal("90000"),
            ),
        ]
        assert MetricsService.compute_avg_mismatch_amount(results) == 10000.0

    def test_multiple_mismatches(self) -> None:
        results = [
            _FakeResult(
                ReconciliationStatus.AMOUNT_MISMATCH,
                Decimal("100000"),
                Decimal("90000"),
            ),
            _FakeResult(
                ReconciliationStatus.AMOUNT_MISMATCH,
                Decimal("200000"),
                Decimal("180000"),
            ),
        ]
        # (10000 + 20000) / 2 = 15000
        assert MetricsService.compute_avg_mismatch_amount(results) == 15000.0


class TestCountByStatus:
    """Test count_by_status method."""

    def test_empty(self) -> None:
        assert MetricsService.count_by_status([]) == {}

    def test_counts(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH),
        ]
        counts = MetricsService.count_by_status(results)
        assert counts == {"MATCHED": 2, "AMOUNT_MISMATCH": 1}


class TestMetricsIsSingleSourceOfTruth:
    """Verify that MetricsService is the only place computing stats."""

    def test_compute_summary_returns_summary_result(self) -> None:
        """Ensure compute_summary returns proper SummaryResult."""
        results = [_FakeResult(ReconciliationStatus.MATCHED)]
        summary = MetricsService.compute_summary(results, "MOMO", "2024-07-07")
        assert isinstance(summary, SummaryResult)

    def test_grouping_engine_pure_function(self) -> None:
        """Verify GroupingEngine.group is deterministic."""
        results = [
            _FakeResult(ReconciliationStatus.MATCHED),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH),
        ]
        run1 = GroupingEngine.group(results)
        run2 = GroupingEngine.group(results)
        assert run1 == run2
