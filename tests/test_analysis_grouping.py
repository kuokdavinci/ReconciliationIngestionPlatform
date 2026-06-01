"""Tests for GroupingEngine — rule-based grouping of reconciliation results."""

from decimal import Decimal

import pytest

from src.analysis.grouping import GroupingEngine
from src.analysis.schemas import GroupCriteria, GroupResult
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


class TestGroupByStatus:
    """Test grouping by reconciliation status."""

    def test_empty_results(self) -> None:
        results = GroupingEngine.group([])
        assert results == []

    def test_all_matched(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000"))
            for _ in range(100)
        ]
        groups = GroupingEngine.group(results)
        assert len(groups) == 1
        assert groups[0].key == "MATCHED"
        assert groups[0].count == 100
        assert groups[0].percentage == 100.0

    def test_mixed_statuses(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000")),
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("200000")),
            _FakeResult(ReconciliationStatus.AMOUNT_MISMATCH, Decimal("50000"), Decimal("45000")),
            _FakeResult(ReconciliationStatus.STATUS_MISMATCH, Decimal("30000")),
            _FakeResult(ReconciliationStatus.MISSING_INTERNAL),
        ]
        groups = GroupingEngine.group(results)
        assert len(groups) == 4

        status_map = {g.key: g for g in groups}
        assert status_map["MATCHED"].count == 2
        assert status_map["MATCHED"].percentage == 40.0
        assert status_map["AMOUNT_MISMATCH"].count == 1
        assert status_map["AMOUNT_MISMATCH"].percentage == 20.0
        assert status_map["STATUS_MISMATCH"].count == 1
        assert status_map["MISSING_INTERNAL"].count == 1

    def test_amount_difference_details_for_mismatch(self) -> None:
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
        groups = GroupingEngine.group(results)
        assert len(groups) == 1
        details = groups[0].details
        assert details["avg_difference"] == 15000.0
        assert details["min_difference"] == 10000.0
        assert details["max_difference"] == 20000.0

    def test_no_difference_details_for_matched(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000")),
        ]
        groups = GroupingEngine.group(results)
        assert groups[0].details == {}

    def test_total_amount_accumulation(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000")),
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("200000")),
        ]
        groups = GroupingEngine.group(results)
        assert groups[0].total_amount == 300000.0


class TestGroupByAmountRange:
    """Test grouping by amount range."""

    def test_empty_results(self) -> None:
        results = GroupingEngine.group_by_amount_range([])
        assert results == []

    def test_ranges(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("50000")),       # 0-100k
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("500000")),      # 100k-1M
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("5000000")),     # 1M+
        ]
        groups = GroupingEngine.group_by_amount_range(results)
        assert len(groups) == 3

        range_map = {g.key: g for g in groups}
        assert range_map["0-100k"].count == 1
        assert range_map["100k-1M"].count == 1
        assert range_map["1M+"].count == 1

    def test_skips_none_amount(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MISSING_INTERNAL),
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000")),
        ]
        groups = GroupingEngine.group_by_amount_range(results)
        # Only the one with amount should be grouped
        assert sum(g.count for g in groups) == 1


class TestGroupByPartner:
    """Test grouping by partner."""

    def test_single_partner(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000"), partner="MOMO"),
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("200000"), partner="MOMO"),
        ]
        groups = GroupingEngine.group_by_partner(results)
        assert len(groups) == 1
        assert groups[0].key == "MOMO"
        assert groups[0].count == 2

    def test_multiple_partners(self) -> None:
        results = [
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("100000"), partner="MOMO"),
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("200000"), partner="VNPAY"),
            _FakeResult(ReconciliationStatus.MATCHED, Decimal("300000"), partner="MOMO"),
        ]
        groups = GroupingEngine.group_by_partner(results)
        assert len(groups) == 2

        partner_map = {g.key: g for g in groups}
        assert partner_map["MOMO"].count == 2
        assert partner_map["VNPAY"].count == 1


class TestPercentageComputation:
    """Test percentage calculation edge cases."""

    def test_zero_total(self) -> None:
        """Zero total should not cause division by zero."""
        groups = GroupingEngine.group([])
        assert groups == []

    def test_percentage_rounding(self) -> None:
        results = [_FakeResult(ReconciliationStatus.MATCHED) for _ in range(3)]
        results.append(_FakeResult(ReconciliationStatus.AMOUNT_MISMATCH))
        groups = GroupingEngine.group(results)
        status_map = {g.key: g for g in groups}
        assert status_map["MATCHED"].percentage == 75.0
        assert status_map["AMOUNT_MISMATCH"].percentage == 25.0
