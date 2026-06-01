"""Rule-based grouping engine for reconciliation results.

Pure functions — no IO, deterministic.
Groups ReconciliationResult objects by status, partner, amount_range.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from src.analysis.schemas import GroupCriteria, GroupResult
from src.core.enums import ReconciliationStatus


# Amount range buckets (in VND — adjust as needed)
AMOUNT_RANGES = [
    (0, 100_000, "0-100k"),
    (100_000, 1_000_000, "100k-1M"),
    (1_000_000, float("inf"), "1M+"),
]


@dataclass
class _GroupBucket:
    """Internal accumulator for grouping computations."""

    key: str
    count: int = 0
    total_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    differences: list[Decimal] = field(default_factory=list)


def _get_amount_range_label(amount: Decimal) -> str:
    """Categorize an amount into a range label.

    Args:
        amount: Transaction amount.

    Returns:
        Range label string (e.g. '0-100k', '100k-1M', '1M+').
    """
    amount_float = float(amount)
    for min_val, max_val, label in AMOUNT_RANGES:
        if min_val <= amount_float < max_val:
            return label
    return AMOUNT_RANGES[-1][2]  # fallback to highest range


def _compute_percentage(count: int, total: int) -> float:
    """Compute percentage with safe division.

    Args:
        count: Part value.
        total: Total value.

    Returns:
        Percentage rounded to 2 decimal places.
    """
    if total == 0:
        return 0.0
    return round((count / total) * 100, 2)


def _compute_difference_details(bucket: _GroupBucket) -> dict[str, Any]:
    """Compute difference statistics for a group bucket.

    Args:
        bucket: Group accumulator with collected differences.

    Returns:
        Dict with avg_difference, min_difference, max_difference.
    """
    if not bucket.differences:
        return {}
    return {
        "avg_difference": round(float(sum(bucket.differences) / len(bucket.differences)), 2),
        "min_difference": float(min(bucket.differences)),
        "max_difference": float(max(bucket.differences)),
    }


class GroupingEngine:
    """Groups reconciliation results by various criteria.

    Pure function class — no IO, deterministic, no external state.
    """

    @staticmethod
    def group(
        results: list[Any],
        criteria: Optional[GroupCriteria] = None,
    ) -> list[GroupResult]:
        """Group reconciliation results by status.

        Args:
            results: List of objects with reconciliation_status and
                     partner_amount/internal_amount attributes.
            criteria: Optional filter criteria (currently unused —
                      grouping always uses status as primary key).

        Returns:
            List of GroupResult objects, one per status group.
        """
        total = len(results)
        buckets: dict[str, _GroupBucket] = {}

        for r in results:
            status = r.reconciliation_status.value if hasattr(r.reconciliation_status, "value") else str(r.reconciliation_status)

            if status not in buckets:
                buckets[status] = _GroupBucket(key=status)

            bucket = buckets[status]
            bucket.count += 1

            # Use partner amount if available, else internal amount
            amount = getattr(r, "partner_amount", None) or getattr(r, "internal_amount", None)
            if amount is not None:
                bucket.total_amount += amount if isinstance(amount, Decimal) else Decimal(str(amount))

            # Track amount differences for mismatch statuses
            if status in (
                ReconciliationStatus.AMOUNT_MISMATCH,
                ReconciliationStatus.MULTIPLE_MISMATCH,
            ):
                partner_amt = getattr(r, "partner_amount", None)
                internal_amt = getattr(r, "internal_amount", None)
                if partner_amt is not None and internal_amt is not None:
                    diff = abs(
                        (partner_amt if isinstance(partner_amt, Decimal) else Decimal(str(partner_amt)))
                        - (internal_amt if isinstance(internal_amt, Decimal) else Decimal(str(internal_amt)))
                    )
                    bucket.differences.append(diff)

        return [
            GroupResult(
                key=bucket.key,
                count=bucket.count,
                percentage=_compute_percentage(bucket.count, total),
                total_amount=float(bucket.total_amount),
                details=_compute_difference_details(bucket),
            )
            for bucket in buckets.values()
        ]

    @staticmethod
    def group_by_amount_range(results: list[Any]) -> list[GroupResult]:
        """Group reconciliation results by amount range.

        Args:
            results: List of objects with partner_amount attribute.

        Returns:
            List of GroupResult objects, one per amount range.
        """
        total = len(results)
        buckets: dict[str, _GroupBucket] = {}

        for r in results:
            amount = getattr(r, "partner_amount", None)
            if amount is None:
                continue
            amount_decimal = amount if isinstance(amount, Decimal) else Decimal(str(amount))
            label = _get_amount_range_label(amount_decimal)

            if label not in buckets:
                buckets[label] = _GroupBucket(key=label)

            bucket = buckets[label]
            bucket.count += 1
            bucket.total_amount += amount_decimal

        return [
            GroupResult(
                key=bucket.key,
                count=bucket.count,
                percentage=_compute_percentage(bucket.count, total),
                total_amount=float(bucket.total_amount),
            )
            for bucket in buckets.values()
        ]

    @staticmethod
    def group_by_partner(results: list[Any]) -> list[GroupResult]:
        """Group reconciliation results by partner identifier.

        Note: In the current architecture, results are already filtered
        by partner before reaching this layer. This method is provided
        for future multi-partner analysis.

        Args:
            results: List of objects with a partner attribute.

        Returns:
            List of GroupResult objects, one per partner.
        """
        total = len(results)
        buckets: dict[str, _GroupBucket] = {}

        for r in results:
            partner = getattr(r, "partner", "unknown")

            if partner not in buckets:
                buckets[partner] = _GroupBucket(key=partner)

            bucket = buckets[partner]
            bucket.count += 1

            amount = getattr(r, "partner_amount", None)
            if amount is not None:
                amount_decimal = amount if isinstance(amount, Decimal) else Decimal(str(amount))
                bucket.total_amount += amount_decimal

        return [
            GroupResult(
                key=bucket.key,
                count=bucket.count,
                percentage=_compute_percentage(bucket.count, total),
                total_amount=float(bucket.total_amount),
            )
            for bucket in buckets.values()
        ]
