"""Bounded source evidence attached to review packets."""

from datetime import datetime
from typing import Any

from src.core.utils import business_day_bounds
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository


def _serialize_internal_row(row: Any) -> dict[str, Any]:
    status = getattr(row.status, "value", row.status)
    transaction_time = getattr(row, "transaction_time", None)
    return {
        "id": str(getattr(row, "id", "")),
        "partnerTxnId": str(getattr(row, "partner_txn_id", "")),
        "amount": str(getattr(row, "amount", "")),
        "currency": str(getattr(row, "currency", "")),
        "status": str(status),
        "transactionTime": transaction_time.isoformat()
        if isinstance(transaction_time, datetime)
        else str(transaction_time or ""),
    }


async def build_internal_review_evidence(
    db: Any,
    *,
    partner: str,
    reconciliation_date: datetime | None,
    record_count: int | None = None,
    sample_limit: int = 10,
    repository: Any | None = None,
) -> dict[str, Any]:
    """Load a bounded internal-DB sample without storing the full table in Mongo."""

    safe_count = max(int(record_count or 0), 0)
    if reconciliation_date is None or safe_count == 0:
        return {"recordCount": safe_count, "sample": []}
    start, end = business_day_bounds(reconciliation_date)
    try:
        reader = repository or InternalTransactionRepository(db)
        rows = await reader.find_by_partner_and_date_range(
            partner,
            start,
            end,
            limit=max(sample_limit, 0),
        )
    except Exception:
        rows = []
    return {
        "recordCount": safe_count,
        "sample": [_serialize_internal_row(row) for row in rows[:sample_limit]],
    }
