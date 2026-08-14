from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.review.evidence import build_internal_review_evidence
from src.core.business_day import business_day_bounds


def test_business_day_bounds_treats_mongo_naive_timestamps_as_utc():
    start, end = business_day_bounds(datetime(2026, 8, 10, 17, 0))

    assert start.isoformat() == "2026-08-11T00:00:00+07:00"
    assert end.isoformat() == "2026-08-11T23:59:59.999999+07:00"


@pytest.mark.asyncio
async def test_internal_review_evidence_contains_bounded_source_rows_and_business_day():
    repository = MagicMock()
    repository.find_by_partner_and_date_range = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="internal-1",
                partner_txn_id="VTP-001",
                amount="100000",
                currency="VND",
                status=SimpleNamespace(value="SUCCESS"),
                transaction_time=datetime(2026, 8, 9, 17, 5),
            )
        ]
    )

    with patch(
        "src.application.review.evidence.InternalTransactionRepository",
        return_value=repository,
    ):
        evidence = await build_internal_review_evidence(
            MagicMock(),
            partner="VIETTELPAY",
            reconciliation_date=datetime(2026, 8, 10, tzinfo=UTC),
            record_count=1,
        )

    start, end = repository.find_by_partner_and_date_range.await_args.args[1:]
    assert start.isoformat() == "2026-08-10T00:00:00+07:00"
    assert end.isoformat() == "2026-08-10T23:59:59.999999+07:00"
    assert evidence["recordCount"] == 1
    assert evidence["sample"] == [
        {
            "id": "internal-1",
            "partnerTxnId": "VTP-001",
            "amount": "100000",
            "currency": "VND",
            "status": "SUCCESS",
            "transactionTime": "2026-08-09T17:05:00",
        }
    ]
