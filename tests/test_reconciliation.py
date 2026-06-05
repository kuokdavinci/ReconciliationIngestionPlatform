"""Unit and integration tests for the Reconciliation Engine."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.core.enums import ReconciliationStatus, TransactionStatus
from src.models.data_container import DataContainer, PartnerData
from src.models.internal_transaction import InternalTransaction
from src.models.reconciliation_result import ReconciliationResult
from src.reconciliation.engine import ReconciliationEngine


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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert results == []
    engine._result_repo.collection.delete_many.assert_not_called()
    engine._result_repo.insert_many.assert_not_called()


@pytest.mark.asyncio
async def test_reconciliation_incremental_scope_ignores_unrelated_internal_rows(mock_db):
    """Incremental scope should only reconcile against keys present in the file."""
    engine = ReconciliationEngine(mock_db)

    recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
    partner = "MOMO"
    source_file_id = "00000000-0000-0000-0000-000000000001"

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

    matched_internal = InternalTransaction(
        _id="int_01",
        partner=partner,
        partnerTxnId="trace_01",
        amount=Decimal("150000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )
    unrelated_internal = InternalTransaction(
        _id="int_02",
        partner=partner,
        partnerTxnId="trace_02",
        amount=Decimal("90000"),
        status=TransactionStatus.SUCCESS,
        transactionTime=recon_date,
    )

    file_collection = MagicMock()
    file_collection.find_one = AsyncMock(return_value={"_id": source_file_id, "scopeType": "INCREMENTAL_APPEND"})
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: file_collection if name == "reconciliation_file" else MagicMock())

    engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
    engine._internal_repo.find_many = AsyncMock(return_value=[matched_internal, unrelated_internal])
    engine._result_repo.collection.delete_many = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date, source_file_id=source_file_id)

    assert len(results) == 1
    assert results[0].reconciliation_status == ReconciliationStatus.MATCHED
    engine._result_repo.collection.delete_many.assert_called_once_with({
        "partner": partner,
        "date": "2024-07-07",
        "sourceFileId": source_file_id,
    })
    assert results[0].source_file_id == source_file_id
    assert results[0].scope_type == "INCREMENTAL_APPEND"


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
    engine._result_repo.collection.delete_many = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date)

    assert len(results) == 1
    engine._result_repo.collection.delete_many.assert_called_once_with({
        "partner": partner,
        "date": "2024-07-07",
    })


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
    engine._result_repo.collection.delete_many = AsyncMock()
    engine._result_repo.insert_many = AsyncMock()

    results = await engine.reconcile(partner, recon_date, source_file_id=source_file_id)

    assert len(results) == 1
    engine._result_repo.collection.delete_many.assert_called_once_with({
        "partner": partner,
        "date": "2024-07-07",
        "$or": [
            {"sourceFileId": source_file_id},
            {"partnerTxnId": {"$in": ["trace_01"]}},
        ],
    })
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
    engine._result_repo.collection.delete_many = AsyncMock()
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
