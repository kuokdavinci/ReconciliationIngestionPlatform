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
