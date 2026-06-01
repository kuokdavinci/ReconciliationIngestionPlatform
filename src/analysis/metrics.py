"""Metrics service — single source of truth for reconciliation statistics.

Pure functions — no IO, deterministic.
All stats are computed here; reporter and alerter MUST NOT duplicate computation.

Enforces: MetricsService is the ONLY place where mismatch_rate,
total_volume, avg_mismatch_amount, count_by_status are calculated.
"""

from decimal import Decimal
from typing import Any

from src.analysis.schemas import GroupResult, SummaryResult
from src.core.enums import ReconciliationStatus


def _safe_divide(numerator: float | Decimal, denominator: float | Decimal) -> float:
    """Safe division returning 0.0 on zero denominator.

    Args:
        numerator: Dividend.
        denominator: Divisor.

    Returns:
        Quotient rounded to 2 decimal places, or 0.0 if denominator is zero.
    """
    denom = float(denominator) if not isinstance(denominator, float) else denominator
    num = float(numerator) if not isinstance(numerator, float) else numerator
    if denom == 0:
        return 0.0
    return round(num / denom, 2)


class MetricsService:
    """Single source of truth for all reconciliation statistics.

    Pure function class — no IO, no external state, deterministic.
    All consumers (reporter, alerter, insights) MUST read from here.
    """

    @staticmethod
    def compute_summary(
        results: list[Any],
        partner: str,
        date: str,
    ) -> SummaryResult:
        """Compute aggregated summary metrics for a partner on a given date.

        Args:
            results: List of ReconciliationResult objects.
            partner: Partner identifier.
            date: Date string (YYYY-MM-DD).

        Returns:
            SummaryResult with total_transactions, matched count,
            mismatch_rate, total_amount_mismatch, and by_status counts.
        """
        total = len(results)
        by_status: dict[str, int] = {}
        matched = 0
        total_mismatch_amount = Decimal("0")

        for r in results:
            status = r.reconciliation_status.value if hasattr(r.reconciliation_status, "value") else str(r.reconciliation_status)
            by_status[status] = by_status.get(status, 0) + 1

            if status == ReconciliationStatus.MATCHED:
                matched += 1

            # Accumulate mismatch amounts for mismatch statuses
            if status in (
                ReconciliationStatus.AMOUNT_MISMATCH,
                ReconciliationStatus.MULTIPLE_MISMATCH,
                ReconciliationStatus.STATUS_MISMATCH,
            ):
                partner_amt = getattr(r, "partner_amount", None)
                internal_amt = getattr(r, "internal_amount", None)
                if partner_amt is not None and internal_amt is not None:
                    diff = abs(
                        (partner_amt if isinstance(partner_amt, Decimal) else Decimal(str(partner_amt)))
                        - (internal_amt if isinstance(internal_amt, Decimal) else Decimal(str(internal_amt)))
                    )
                    total_mismatch_amount += diff

        mismatch_count = total - matched
        mismatch_rate = _safe_divide(mismatch_count * 100, total)

        return SummaryResult(
            partner=partner,
            date=date,
            total_transactions=total,
            matched=matched,
            mismatch_rate=mismatch_rate,
            total_amount_mismatch=float(total_mismatch_amount),
            by_status=by_status,
        )

    @staticmethod
    def summary_from_groups(
        groups: list[GroupResult],
        results: list[Any],
    ) -> dict[str, Any]:
        """Compute cross-group statistics from grouped results.

        Useful for deriving stats that span multiple groups,
        e.g. total mismatch amount across all mismatch groups.

        Args:
            groups: List of GroupResult from GroupingEngine.
            results: Original reconciliation results.

        Returns:
            Dict with cross-group statistics:
            - total_groups: number of groups
            - largest_group: key of the group with highest count
            - largest_group_count: count of largest group
            - total_mismatch_amount: sum of amounts in mismatch groups
        """
        if not groups:
            return {
                "total_groups": 0,
                "largest_group": None,
                "largest_group_count": 0,
                "total_mismatch_amount": 0.0,
            }

        largest = max(groups, key=lambda g: g.count)
        mismatch_statuses = {
            ReconciliationStatus.AMOUNT_MISMATCH,
            ReconciliationStatus.STATUS_MISMATCH,
            ReconciliationStatus.MULTIPLE_MISMATCH,
            ReconciliationStatus.MISSING_INTERNAL,
            ReconciliationStatus.MISSING_PARTNER,
        }

        total_mismatch_amount = sum(
            g.total_amount for g in groups if g.key in mismatch_statuses
        )

        return {
            "total_groups": len(groups),
            "largest_group": largest.key,
            "largest_group_count": largest.count,
            "total_mismatch_amount": total_mismatch_amount,
        }

    @staticmethod
    def compute_mismatch_rate(results: list[Any]) -> float:
        """Compute mismatch rate as a percentage.

        Args:
            results: List of ReconciliationResult objects.

        Returns:
            Mismatch rate percentage (0.0-100.0).
        """
        if not results:
            return 0.0
        matched = sum(
            1 for r in results
            if (r.reconciliation_status.value if hasattr(r.reconciliation_status, "value") else str(r.reconciliation_status))
            == ReconciliationStatus.MATCHED
        )
        return _safe_divide((len(results) - matched) * 100, len(results))

    @staticmethod
    def compute_avg_mismatch_amount(results: list[Any]) -> float:
        """Compute average absolute amount difference for mismatched results.

        Args:
            results: List of ReconciliationResult objects.

        Returns:
            Average mismatch amount, or 0.0 if no mismatches.
        """
        mismatches = [
            r for r in results
            if (r.reconciliation_status.value if hasattr(r.reconciliation_status, "value") else str(r.reconciliation_status))
            in (
                ReconciliationStatus.AMOUNT_MISMATCH,
                ReconciliationStatus.MULTIPLE_MISMATCH,
            )
        ]
        if not mismatches:
            return 0.0

        total_diff = Decimal("0")
        for r in mismatches:
            partner_amt = getattr(r, "partner_amount", None)
            internal_amt = getattr(r, "internal_amount", None)
            if partner_amt is not None and internal_amt is not None:
                diff = abs(
                    (partner_amt if isinstance(partner_amt, Decimal) else Decimal(str(partner_amt)))
                    - (internal_amt if isinstance(internal_amt, Decimal) else Decimal(str(internal_amt)))
                )
                total_diff += diff

        return _safe_divide(total_diff, len(mismatches))

    @staticmethod
    def count_by_status(results: list[Any]) -> dict[str, int]:
        """Count results by reconciliation status.

        Args:
            results: List of ReconciliationResult objects.

        Returns:
            Dict mapping status name to count.
        """
        counts: dict[str, int] = {}
        for r in results:
            status = r.reconciliation_status.value if hasattr(r.reconciliation_status, "value") else str(r.reconciliation_status)
            counts[status] = counts.get(status, 0) + 1
        return counts
