"""Unit and integration tests for the Reconciliation Engine."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.core.enums import ReconciliationStatus, TransactionStatus
from src.domain.internal_transaction.models import InternalTransaction
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.reconciliation.engine import ReconciliationEngine
from src.reconciliation.keys import normalize_reconciliation_key


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock for AsyncIOMotorDatabase."""
    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name: MagicMock())
    return db


@pytest.mark.asyncio
async def test_reconciliation_matched(mock_db):
    """Test scenario where partner transaction matches internal transaction exactly."""
    engine = ReconciliationEngine(mock_db)

    # 1. Setup mock data
    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    # Partner Record
    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    # Internal Record
    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    # Mock repositories
    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock(return_value=1)

    # 2. Run reconciliation
    results = await engine.reconcile(partner, recon_date)

    # 3. Asserts
    assert len(results) == 1
    result = results[0]
    assert result.partner_txn_id == "trace_01"
    assert result.reconciliation_status == ReconciliationStatus.MATCHED
    assert result.partner_amount == Decimal("150000")
    assert result.internal_amount == Decimal("150000")
    assert result.partner_status == "Thành công"
    assert result.internal_status == TransactionStatus.SUCCESS


def test_reconciliation_uses_business_timezone_day_bounds():
    start, end = ReconciliationEngine._business_day_bounds(
        datetime(2026, 8, 10, tzinfo=timezone.utc)
    )

    assert start == datetime(2026, 8, 9, 17, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 10, 16, 59, 59, 999999, tzinfo=timezone.utc)


def test_reconciliation_treats_mongo_naive_dates_as_utc_instants():
    start, end = ReconciliationEngine._business_day_bounds(datetime(2026, 8, 10, 17))

    assert start == datetime(2026, 8, 10, 17, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 11, 16, 59, 59, 999999, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("", "  ", "vsp-1", "partner-1"), "vsp-1"),
        (("  trace-1  ", "vsp-1", "partner-1"), "trace-1"),
        ((None, "", "partner-1"), "partner-1"),
        ((" ", None, ""), None),
    ],
)
def test_normalize_reconciliation_key_uses_trimmed_non_empty_fallback(candidates, expected):
    assert normalize_reconciliation_key(*candidates) == expected


@pytest.mark.asyncio
async def test_reconciliation_amount_mismatch(mock_db):
    """Test scenario where amounts differ between partner and internal."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("149000"),  # Mismatch amount
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.AMOUNT_MISMATCH


@pytest.mark.asyncio
async def test_reconciliation_status_mismatch(mock_db):
    """Test scenario where statuses differ (but amount is correct)."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thất bại",  # Normalized -> FAILED
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,  # SUCCESS
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.STATUS_MISMATCH


@pytest.mark.asyncio
async def test_reconciliation_missing_internal(mock_db):
    """Test scenario where partner record exists but no internal record."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.MISSING_INTERNAL


@pytest.mark.asyncio
async def test_reconciliation_missing_partner(mock_db):
    """Test scenario where internal record exists but no partner record."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[])
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.MISSING_PARTNER


@pytest.mark.asyncio
async def test_reconciliation_ignores_pending_internal_for_missing_partner(mock_db):
    """Pending internal rows should not produce MISSING_PARTNER results."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    pending_internal_record = InternalTransaction(
        _id="int_pending",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.PENDING,
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[])
    engine._internal_repo.find_many = AsyncMock(return_value=[pending_internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert results == []
    engine._result_repo.delete_by_partner_and_date.assert_called_once()
    engine._result_repo.insert_many.assert_not_called()


@pytest.mark.asyncio
async def test_reconciliation_incremental_scope_ignores_unrelated_internal_rows(mock_db):
    """Incremental append should ignore out-of-scope internal rows already in DB."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"
    source_file_id = "00000000-0000-0000-0000-000000000001"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId=source_file_id,
            partnerData=PartnerData(
                _id=f"txn_{index:02d}",
                trace=f"trace_{index:02d}",
                status="Thành công",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for index in range(20)
    ]
    internal_records = [
        InternalTransaction(
            _id=f"int_{index:02d}",
            partner=partner,
            partnerTxnId=f"trace_{index:02d}",
            amount=Decimal("150000"),
            status=TransactionStatus.SUCCESS,
            transactionTime=recon_date,
        )
        for index in range(40)
    ]

    file_collection = MagicMock()
    file_collection.find_one = AsyncMock(return_value={"_id": source_file_id, "scopeType": "INCREMENTAL_APPEND"})
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: file_collection if name == "reconciliation_file" else MagicMock())

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=internal_records)
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date, source_file_id=source_file_id)

    assert len(results) == 20
    assert {result.partner_txn_id for result in results} == {f"trace_{index:02d}" for index in range(20)}
    assert all(result.reconciliation_status == ReconciliationStatus.MATCHED for result in results)
    delete_call = engine._result_repo.delete_by_partner_and_date.call_args
    assert delete_call.args == (partner, "2024-07-07")
    assert delete_call.kwargs["source_file_id"] == source_file_id
    assert set(delete_call.kwargs["partner_txn_ids"]) == {
        f"trace_{index:02d}" for index in range(20)
    }
    assert results[0].source_file_id == source_file_id
    assert results[0].scope_type == "INCREMENTAL_APPEND"


@pytest.mark.asyncio
async def test_reconciliation_incremental_append_uses_current_batch_only(mock_db):
    """Incremental append should reconcile only the current source batch."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"
    wave1_source_file_id = "00000000-0000-0000-0000-000000000001"
    wave2_source_file_id = "00000000-0000-0000-0000-000000000002"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId=wave1_source_file_id if index < 20 else wave2_source_file_id,
            partnerData=PartnerData(
                _id=f"txn_{index:02d}",
                trace=f"trace_{index:02d}",
                status="Thành công",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for index in range(40)
    ]
    internal_records = [
        InternalTransaction(
            _id=f"int_{index:02d}",
            partner=partner,
            partnerTxnId=f"trace_{index:02d}",
            amount=Decimal("150000"),
            status=TransactionStatus.SUCCESS,
            transactionTime=recon_date,
        )
        for index in range(40)
    ]

    file_collection = MagicMock()
    file_collection.find_one = AsyncMock(return_value={"_id": wave2_source_file_id, "scopeType": "INCREMENTAL_APPEND"})
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: file_collection if name == "reconciliation_file" else MagicMock())

    engine._data_repo.find_many = AsyncMock(return_value=partner_records[20:])
    engine._internal_repo.find_many = AsyncMock(return_value=internal_records)
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date, source_file_id=wave2_source_file_id)

    assert len(results) == 20
    assert {result.partner_txn_id for result in results} == {
        f"trace_{index:02d}" for index in range(20, 40)
    }
    assert all(result.reconciliation_status == ReconciliationStatus.MATCHED for result in results)
    delete_call = engine._result_repo.delete_by_partner_and_date.call_args
    assert delete_call.args == (partner, "2024-07-07")
    assert delete_call.kwargs["source_file_id"] == wave2_source_file_id
    assert set(delete_call.kwargs["partner_txn_ids"]) == {
        f"trace_{index:02d}" for index in range(20, 40)
    }


@pytest.mark.asyncio
async def test_reconciliation_full_snapshot_replaces_entire_day_slice(mock_db):
    """Full snapshot should still replace the whole day slice."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )
    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    engine._result_repo.delete_by_partner_and_date.assert_called_once_with(partner, "2024-07-07")


@pytest.mark.asyncio
async def test_reconciliation_replacement_scope_replaces_prior_keys(mock_db):
    """Replacement scope should delete prior rows for the same key set across files."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"
    source_file_id = "00000000-0000-0000-0000-000000000009"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId=source_file_id,
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )
    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    file_collection = MagicMock()
    file_collection.find_one = AsyncMock(return_value={"_id": source_file_id, "scopeType": "REPLACEMENT"})
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: file_collection if name == "reconciliation_file" else MagicMock())

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date, source_file_id=source_file_id)

    assert len(results) == 1
    engine._result_repo.delete_by_partner_and_date.assert_called_once_with(partner, "2024-07-07", source_file_id=source_file_id, partner_txn_ids=["trace_01"])
    assert results[0].scope_type == "REPLACEMENT"


@pytest.mark.asyncio
async def test_reconciliation_duplicate_internal_handling(mock_db):
    """Test that duplicate internal records keep the latest based on updatedAt."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    # Two internal records with same partnerTxnId but different updated_at
    old_internal_record = InternalTransaction(
        _id="int_old",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("200000"),  # old incorrect amount
        status=TransactionStatus.FAILED,
        transactionTime=recon_date,
        createdAt=recon_date,
        updatedAt=datetime(2024, 7, 7, 10, 0, 0, tzinfo=timezone.utc),
    )

    new_internal_record = InternalTransaction(
        _id="int_new",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),  # new correct amount
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
        createdAt=recon_date,
        updatedAt=datetime(2024, 7, 7, 12, 0, 0, tzinfo=timezone.utc),
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(
        return_value=[old_internal_record, new_internal_record]
    )
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    # Should use the new record which matches partner record exactly
    assert results[0].reconciliation_status == ReconciliationStatus.MATCHED
    assert results[0].internal_record_id == "int_new"


@pytest.mark.asyncio
async def test_reconciliation_skipped_empty_status(mock_db):
    """A partner record with empty status is skipped by the pre-check guard."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_01",
            trace="trace_01",
            status="",  # empty status — should be skipped after guard
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    # The record with empty status is skipped, but creates an UNMAPPED_SKIPPED result
    # (for stats visibility per D-05)
    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.UNMAPPED_SKIPPED


@pytest.mark.asyncio
async def test_reconciliation_all_records_skipped(mock_db):
    """Multiple partner records all with empty status — all skipped."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_0{i}",
                trace=f"trace_0{i}",
                status="",  # empty status
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(3)
    ]

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=[])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    # After guard: all 3 records skipped, each produces UNMAPPED_SKIPPED result
    assert len(results) == 3
    for r in results:
        assert r.reconciliation_status == ReconciliationStatus.UNMAPPED_SKIPPED


@pytest.mark.asyncio
async def test_reconciliation_mixed_valid_and_skipped(mock_db):
    """3 partner records: 1 valid (matched), 2 with empty status (skipped)."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    # Valid record
    valid_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_valid",
            trace="trace_valid",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    # Two invalid records with empty status
    invalid_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_invalid_{i}",
                trace=f"trace_invalid_{i}",
                status="",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(2)
    ]

    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_valid",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[valid_record] + invalid_records)
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    # After guard: 2 skipped (UNMAPPED_SKIPPED), 1 valid (MATCHED)
    assert len(results) == 3
    matched = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED]
    skipped = [r for r in results if r.reconciliation_status == ReconciliationStatus.UNMAPPED_SKIPPED]
    assert len(matched) == 1
    assert len(skipped) == 2


@pytest.mark.asyncio
async def test_skipped_record_creates_unmapped_skipped(mock_db):
    """A skipped record creates a ReconciliationResult with UNMAPPED_SKIPPED status."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_skip_01",
            trace="trace_skip_01",
            status="",  # empty status triggers pre-check skip
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.UNMAPPED_SKIPPED
    assert results[0].partner_record_id == str(partner_record.id)


@pytest.mark.asyncio
async def test_mixed_skipped_and_matched_guard(mock_db):
    """3 records: 1 valid matched, 2 skipped — 3 total results with correct statuses."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    # Valid record
    valid_record = DataContainer(
        identify=partner,
        workflowType="UPC",
        reconciliationDate=recon_date,
        sourceFileId="00000000-0000-0000-0000-000000000001",
        partnerData=PartnerData(
            _id="txn_valid",
            trace="trace_valid",
            status="Thành công",
            amount=Decimal("150000"),
            currency="VND",
        ),
    )

    # Skipped records (empty status)
    skipped_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_skip_{i}",
                trace=f"trace_skip_{i}",
                status="",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(2)
    ]

    internal_record = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_valid",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    engine._data_repo.find_many = AsyncMock(return_value=[valid_record] + skipped_records)
    engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 3

    # Find which result is MATCHED
    matched = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED]
    skipped = [r for r in results if r.reconciliation_status == ReconciliationStatus.UNMAPPED_SKIPPED]
    assert len(matched) == 1
    assert len(skipped) == 2

    # Verify insert_many receives all 3 results (including skipped for stats)
    engine._result_repo.insert_many.assert_called_once()
    inserted = engine._result_repo.insert_many.call_args[0][0]
    assert len(inserted) == 3


@pytest.mark.asyncio
async def test_reconciliation_flushes_results_in_chunks(mock_db):
    """Large result sets should be inserted in chunks instead of one unbounded batch."""
    engine = ReconciliationEngine(mock_db, partner_batch_size=2, result_batch_size=2)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_{i}",
                trace=f"trace_{i}",
                status="Thành công",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(5)
    ]

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=[])
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 5
    assert all(r.reconciliation_status == ReconciliationStatus.MISSING_INTERNAL for r in results)
    engine._result_repo.delete_by_partner_and_date.assert_called_once_with(partner, "2024-07-07")
    assert engine._result_repo.insert_many.await_count == 3
    inserted_batch_sizes = [
        len(call.args[0]) for call in engine._result_repo.insert_many.await_args_list
    ]
    assert inserted_batch_sizes == [2, 2, 1]


@pytest.mark.asyncio
async def test_parallel_workers_produce_correct_counts(mock_db):
    """Parallel workers should not change total counts vs single worker."""
    engine = ReconciliationEngine(mock_db, write_workers=4, result_batch_size=3)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_{i}",
                trace=f"trace_{i}",
                status="Thành công" if i < 8 else "Thất bại",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(10)
    ]

    internal_records = [
        InternalTransaction(
            _id=f"int_{i}",
            partner=partner,
            partnerTxnId=f"trace_{i}",
            amount=Decimal("150000"),
            status=TransactionStatus.SUCCESS if i < 8 else TransactionStatus.FAILED,
            transactionTime=recon_date,
        )
        for i in range(10)
    ]

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=internal_records)
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock(return_value=1)

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 10
    matched = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED]
    matched_failed = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED_FAILED]
    assert len(matched) == 8
    assert len(matched_failed) == 2

    # Verify multiple batch writes happened (parallel workers)
    assert engine._result_repo.insert_many.await_count >= 3
    assert engine._result_repo.delete_by_partner_and_date.await_count == 1


@pytest.mark.asyncio
async def test_parallel_workers_no_duplicate_results(mock_db):
    """Parallel workers must not produce duplicate reconciliation results."""
    engine = ReconciliationEngine(mock_db, write_workers=4, result_batch_size=2)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_{i}",
                trace=f"trace_{i}",
                status="Thành công",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(20)
    ]

    internal_records = [
        InternalTransaction(
            _id=f"int_{i}",
            partner=partner,
            partnerTxnId=f"trace_{i}",
            amount=Decimal("150000"),
            status=TransactionStatus.SUCCESS,
            transactionTime=recon_date,
        )
        for i in range(20)
    ]

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=internal_records)
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock(return_value=1)

    results = await engine.reconcile(partner, recon_date)

    # Verify no duplicate partner_txn_ids
    result_ids = [r.partner_txn_id for r in results]
    assert len(result_ids) == len(set(result_ids))

    # Verify all records accounted for
    assert len(results) == 20
    matched = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED]
    assert len(matched) == 20


@pytest.mark.asyncio
async def test_parallel_workers_correct_counts_mixed_outcomes(mock_db):
    """Parallel workers produce correct matched/mismatch/unmatched counts."""
    engine = ReconciliationEngine(mock_db, write_workers=4, result_batch_size=2)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    # 5 matched, 2 amount mismatch, 1 status mismatch, 2 missing internal
    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_{i}",
                trace=f"trace_{i}",
                status="Thành công",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(8)
    ]
    # 2 records with amount mismatch
    partner_records.extend([
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_{i}",
                trace=f"trace_{i}",
                status="Thành công",
                amount=Decimal("200000"),
                currency="VND",
            ),
        )
        for i in range(8, 10)
    ])

    internal_records = [
        InternalTransaction(
            _id=f"int_{i}",
            partner=partner,
            partnerTxnId=f"trace_{i}",
            amount=Decimal("150000"),
            status=TransactionStatus.SUCCESS,
            transactionTime=recon_date,
        )
        for i in range(10)
    ]

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=internal_records)
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock(return_value=1)

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 10
    matched = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED]
    amount_mismatch = [r for r in results if r.reconciliation_status == ReconciliationStatus.AMOUNT_MISMATCH]
    assert len(matched) == 8, f"Expected 8 matched, got {len(matched)}"
    assert len(amount_mismatch) == 2, f"Expected 2 amount mismatches, got {len(amount_mismatch)}"


@pytest.mark.asyncio
async def test_parallel_workers_with_unmatched_internal(mock_db):
    """Parallel workers produce correct unmatched internal count."""
    engine = ReconciliationEngine(mock_db, write_workers=4, result_batch_size=2)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"

    partner_records = [
        DataContainer(
            identify=partner,
            workflowType="UPC",
            reconciliationDate=recon_date,
            sourceFileId="00000000-0000-0000-0000-000000000001",
            partnerData=PartnerData(
                _id=f"txn_{i}",
                trace=f"trace_{i}",
                status="Thành công",
                amount=Decimal("150000"),
                currency="VND",
            ),
        )
        for i in range(3)
    ]

    # More internal records than partner records
    internal_records = [
        InternalTransaction(
            _id=f"int_{i}",
            partner=partner,
            partnerTxnId=f"trace_{i}",
            amount=Decimal("150000"),
            status=TransactionStatus.SUCCESS,
            transactionTime=recon_date,
        )
        for i in range(5)
    ]

    engine._data_repo.find_many = AsyncMock(return_value=partner_records)
    engine._internal_repo.find_many = AsyncMock(return_value=internal_records)
    engine._result_repo.delete_by_partner_and_date = AsyncMock()
    engine._result_repo.insert_many = AsyncMock(return_value=1)

    results = await engine.reconcile(partner, recon_date)

    matched = [r for r in results if r.reconciliation_status == ReconciliationStatus.MATCHED]
    missing_partner = [r for r in results if r.reconciliation_status == ReconciliationStatus.MISSING_PARTNER]

    assert len(results) == 5  # 3 matched + 2 missing partner
    assert len(matched) == 3
    assert len(missing_partner) == 2
