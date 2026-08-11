from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from bson.decimal128 import Decimal128

from src.core.enums import ReconciliationStatus
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.partner_transaction.mappers import (
    data_container_to_row,
    document_to_data_container,
)
from src.infrastructure.postgres.reconciliation_result_mappers import (
    document_to_reconciliation_result,
)


def test_partner_mapper_handles_legacy_aliases_and_decimal128():
    document = DataContainer(
        identify="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime.now(timezone.utc),
        source_file_id=uuid4(),
        partner_data=PartnerData(
            _id="txn-1",
            trace="trace-1",
            status="SUCCESS",
            amount=Decimal("100.25"),
            currency="VND",
        ),
    ).model_dump(by_alias=True)
    document["partnerData"]["amount"] = Decimal128("100.25")

    mapped = document_to_data_container(document)

    assert mapped.partner_data.amount == Decimal("100.25")
    assert mapped.partner_data.id == "txn-1"
    assert "id" not in document


def test_partner_mapper_converts_aware_timestamps_to_utc_naive():
    local_time = datetime(2026, 8, 10, 0, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    document = DataContainer(
        identify="MOMO",
        workflow_type="UPC",
        reconciliation_date=local_time,
        source_file_id=uuid4(),
        partner_data=PartnerData(
            _id="txn-1",
            trace="trace-1",
            status="SUCCESS",
            amount=Decimal("100.25"),
            currency="VND",
        ),
    )

    row = data_container_to_row(document)

    assert row["reconciliation_date"] == datetime(2026, 8, 9, 17, 0)
    assert row["reconciliation_date"].tzinfo is None


def test_reconciliation_result_mapper_handles_legacy_aliases_and_decimal128():
    document = ReconciliationResult(
        _id="result-1",
        partner="MOMO",
        date="2024-01-15",
        partnerTxnId="partner-1",
        reconciliationStatus=ReconciliationStatus.MATCHED,
        partnerAmount=Decimal("100.25"),
    ).model_dump(by_alias=True)
    document["partnerAmount"] = Decimal128("100.25")

    mapped = document_to_reconciliation_result(document)

    assert mapped.partner_amount == Decimal("100.25")
    assert mapped.reconciliation_status is ReconciliationStatus.MATCHED
    assert "id" not in document
