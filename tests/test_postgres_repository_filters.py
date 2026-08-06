import pytest
from decimal import Decimal
from datetime import datetime, timezone
from src.models.reconciliation_result import ReconciliationResult, ReconciliationResultRepository
from src.models.internal_transaction import InternalTransaction, InternalTransactionRepository
from src.core.enums import TransactionStatus
from src.core.enums import ReconciliationStatus
from src.models.postgres import ReconciliationResultTable

class SubscriptableDummy:
    def __getitem__(self, item):
        return None

@pytest.mark.asyncio
async def test_postgres_repository_filters_dict_and_list(setup_postgres_test_db):
    """Test that ReconciliationResultRepository properly parses dict with $in and list for PostgreSQL queries."""
    # Ensure postgres is enabled for testing
    repo = ReconciliationResultRepository(SubscriptableDummy())
    assert not hasattr(repo, "collection")

    # 1. Clean previous data
    from sqlalchemy import delete
    async with repo.engine.begin() as conn:
        await conn.execute(delete(ReconciliationResultTable))

    # 2. Insert dummy records
    records = [
        ReconciliationResult(
            _id="res_01",
            partner="MOMO",
            date="2024-07-07",
            partnerTxnId="partner_txn_01",
            internalTxnId="internal_txn_01",
            partnerAmount=Decimal("1000.0"),
            internalAmount=Decimal("1000.0"),
            partnerStatus="SUCCESS",
            internalStatus="SUCCESS",
            reconciliationStatus=ReconciliationStatus.MATCHED,
            reconciliationRunId="run_1",
            sourceFileId="file_A",
        ),
        ReconciliationResult(
            _id="res_02",
            partner="MOMO",
            date="2024-07-07",
            partnerTxnId="partner_txn_02",
            internalTxnId="internal_txn_02",
            partnerAmount=Decimal("2000.0"),
            internalAmount=Decimal("1500.0"),
            partnerStatus="SUCCESS",
            internalStatus="SUCCESS",
            reconciliationStatus=ReconciliationStatus.AMOUNT_MISMATCH,
            reconciliationRunId="run_2",
            sourceFileId="file_B",
        ),
        ReconciliationResult(
            _id="res_03",
            partner="MOMO",
            date="2024-07-07",
            partnerTxnId="partner_txn_03",
            internalTxnId=None,
            partnerAmount=Decimal("3000.0"),
            internalAmount=None,
            partnerStatus="SUCCESS",
            internalStatus=None,
            reconciliationStatus=ReconciliationStatus.MISSING_INTERNAL,
            reconciliationRunId="run_3",
            sourceFileId="file_C",
        ),
    ]
    inserted = await repo.insert_many(records)
    assert inserted == 3

    # 3. Test find_page_by_partner_and_date with dict containing $in
    page, total = await repo.find_page_by_partner_and_date(
        partner="MOMO",
        date="2024-07-07",
        source_file_id={"$in": ["file_A", "file_B"]},
    )
    assert total == 2
    assert len(page) == 2
    assert {r.id for r in page} == {"res_01", "res_02"}

    # Test with raw list
    page, total = await repo.find_page_by_partner_and_date(
        partner="MOMO",
        date="2024-07-07",
        source_file_id=["file_A", "file_B"],
    )
    assert total == 2
    assert len(page) == 2
    assert {r.id for r in page} == {"res_01", "res_02"}

    # Test with single string value
    page, total = await repo.find_page_by_partner_and_date(
        partner="MOMO",
        date="2024-07-07",
        source_file_id="file_C",
    )
    assert total == 1
    assert len(page) == 1
    assert page[0].id == "res_03"

    # Test count_by_status with dict containing $in
    counts = await repo.count_by_status(
        partner="MOMO",
        date="2024-07-07",
        source_file_id={"$in": ["file_A", "file_B"]},
    )
    assert counts.get(ReconciliationStatus.MATCHED.value) == 1
    assert counts.get(ReconciliationStatus.AMOUNT_MISMATCH.value) == 1
    assert counts.get(ReconciliationStatus.MISSING_INTERNAL.value) is None

    # Test get_total_amounts with dict containing $in
    amounts = await repo.get_total_amounts(
        partner="MOMO",
        date="2024-07-07",
        source_file_id={"$in": ["file_A", "file_B"]},
    )
    assert amounts["total_partner_amount"] == Decimal("3000.0")
    assert amounts["total_internal_amount"] == Decimal("2500.0")


@pytest.mark.asyncio
async def test_internal_transaction_repository_is_postgres_source_of_truth(setup_postgres_test_db):
    repository = InternalTransactionRepository()
    partner = "STEP3_TEST"
    transaction_id = "STEP3_TXN_001"
    transaction = InternalTransaction(
        _id="STEP3_INTERNAL_001",
        partner=partner,
        partnerTxnId=transaction_id,
        amount=Decimal("125000"),
        currency="VND",
        status=TransactionStatus.SUCCESS,
        transactionTime=datetime.now(timezone.utc),
    )

    await repository.delete_by_partner(partner)
    try:
        assert await repository.insert_many([transaction]) == 1
        assert await repository.find_existing_partner_txn_ids(partner, [transaction_id]) == {transaction_id}
    finally:
        assert await repository.delete_by_partner_and_txn_id(partner, transaction_id) == 1
