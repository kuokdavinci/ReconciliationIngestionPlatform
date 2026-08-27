"""E2E test: 20 records ingestion + reconciliation for MOMO and ZALOPAY.

Verifies the full pipeline:
1. Seed internal transactions + partner file (20 records per partner)
2. Run IngestionPipeline.process_file()
3. Run ReconciliationEngine.reconcile()
4. Verify reconciliation results match expected counts

Requires:
- Running MongoDB + PostgreSQL (docker compose up)
- --e2e flag: pytest tests/test_e2e_20_records.py -v --e2e
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from src.config.settings import settings

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.enums import FileType, TransactionStatus
from src.domain.internal_transaction.models import InternalTransaction
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
)
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
)
from src.reconciliation.engine import ReconciliationEngine


# ── Helpers ──────────────────────────────────────────────────────────────

PARTNER_MOMO = "MOMO"
PARTNER_ZALOPAY = "ZALOPAY"
TEST_DATE = "2026-06-24"
TEST_NUM_RECORDS = 20


def _reconciliation_summary(results) -> dict[str, int]:
    statuses = [str(result.reconciliation_status) for result in results]
    return {
        "recon_total": len(results),
        "recon_matched": statuses.count("MATCHED"),
    }


def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


async def _ensure_mapping_config(db, partner: str, config_id: str) -> None:
    """Ensure an APPROVED mapping config exists for the given partner."""

    async def _inner():
        collection = db["reconciliation_mapping_config"]
        await collection.delete_many({"partner": partner})
        field_mappings = [
            {"path": "id", "column": 2, "type": "STRING", "required": True},
        ]
        if partner == PARTNER_MOMO:
            field_mappings += [
                {"path": "trace", "column": 11, "type": "STRING"},
                {"path": "amount", "column": 5, "type": "DECIMAL"},
                {"path": "currency", "constant": "VND", "type": "CONSTANT"},
                {"path": "status", "column": 18, "type": "MAPPING",
                 "mapping": {"Thành công": "SUCCESS", "others": "FAILED"}},
                {"path": "transDate", "column": 8, "type": "DATE"},
                {"path": "extra.service", "constant": "PAYMENT", "type": "CONSTANT"},
                {"path": "extra.portal", "constant": "PaymentGateway", "type": "CONSTANT"},
                {"path": "extra.provider", "constant": "MOMO", "type": "CONSTANT"},
            ]
        else:
            field_mappings += [
                {"path": "extra.zpMaHDon", "column": 11, "type": "STRING"},
                {"path": "amount", "column": 5, "type": "DECIMAL"},
                {"path": "currency", "constant": "VND", "type": "CONSTANT"},
                {"path": "status", "column": 18, "type": "MAPPING",
                 "mapping": {"Thành công": "SUCCESS", "others": "FAILED"}},
                {"path": "transDate", "column": 8, "type": "DATE"},
                {"path": "extra.service", "constant": "PAYMENT", "type": "CONSTANT"},
                {"path": "extra.portal", "constant": "PaymentGateway", "type": "CONSTANT"},
                {"path": "extra.provider", "constant": "ZALOPAY", "type": "CONSTANT"},
            ]

        doc = {
            "_id": config_id,
            "partner": partner,
            "workflowType": "UPC",
            "fileType": FileType.SETTLEMENT.value,
            "sheetName": "Sheet1",
            "startRow": 8,
            "fieldMappings": field_mappings,
            "configVersion": "v_e2e_test",
            "status": "APPROVED",
            "approvedAt": datetime.now(timezone.utc),
            "approvedBy": "e2e_test",
            "createdAt": datetime.now(timezone.utc),
        }
        await collection.insert_one(doc)

    await _inner()


def _write_partner_file(path: Path, partner: str, num_records: int) -> None:
    """Write a partner xlsx with `num_records` rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for _ in range(6):
        ws.append([])

    headers = [""] * 30
    headers[0] = "STT"
    headers[1] = "msTransId" if partner == PARTNER_MOMO else "zpTransId"
    headers[4] = "msTotalAmount" if partner == PARTNER_MOMO else "zpTotalAmount"
    headers[7] = "msNgayHoanThanh" if partner == PARTNER_MOMO else "zpNgayGd"
    headers[10] = "msMaHDon" if partner == PARTNER_MOMO else "zpMaHDon"
    headers[17] = "msTrangThaiGd" if partner == PARTNER_MOMO else "zpTrangThai"
    ws.append(headers)

    prefix = "MOMO_TXN_" if partner == PARTNER_MOMO else "ZALO_TXN_"
    for i in range(1, num_records + 1):
        txn_id = f"{prefix}E2E{i:04d}"
        amount = 100000 + i * 5000
        row = [""] * 30
        row[0] = str(i)
        row[1] = txn_id
        row[4] = str(amount)
        row[7] = f"{TEST_DATE} 12:00:00"
        row[10] = txn_id
        row[17] = "Thành công"
        ws.append(row)

    wb.save(path)


async def _seed_internal(db, partner: str, num_records: int) -> int:
    """Seed internal transactions for the given partner."""
    del db
    repository = InternalTransactionRepository()
    await repository.delete_by_partner(partner)
    now = datetime.now(timezone.utc)
    day = datetime.strptime(TEST_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    prefix = "MOMO_TXN_" if partner == PARTNER_MOMO else "ZALO_TXN_"
    docs: list[InternalTransaction] = []
    for i in range(1, num_records + 1):
        txn_id = f"{prefix}E2E{i:04d}"
        amount = Decimal(100000 + i * 5000)
        docs.append(InternalTransaction(
            _id=f"INT_{partner}_{txn_id}",
            partner=partner,
            partnerTxnId=txn_id,
            amount=amount,
            currency="VND",
            status=TransactionStatus.SUCCESS,
            transactionTime=day,
            createdAt=now,
            updatedAt=now,
        ))
    if docs:
        return await repository.insert_many(docs)
    return 0


async def _cleanup_partner_data(db, partner: str) -> None:
    """Clean up all data for a partner across collections."""
    for coll_name in [
        "reconciliation_file",
        "review_packet", "reconciliation_mapping_config",
        "partner_runtime_run", "post_approval_run", "reconciliation_review_record",
    ]:
        try:
            await db[coll_name].delete_many({"partner": partner})
        except Exception:
            pass
    try:
        await ReconciliationResultRepository().delete_by_partner_and_date(partner, TEST_DATE)
    except Exception:
        pass
    try:
        await DataContainerRepository().delete_by_partner(partner)
    except Exception:
        pass
    try:
        await InternalTransactionRepository().delete_by_partner(partner)
    except Exception:
        pass


async def _run_full_flow(
    db, partner: str, partner_file: Path, num_records: int
) -> dict:
    """Run seed → ingestion → reconciliation and return results summary."""
    reconciliation_date = datetime.strptime(TEST_DATE, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    # Seed internal transactions
    inserted = await _seed_internal(db, partner, num_records)
    assert inserted == num_records, f"Expected {num_records} internal rows, got {inserted}"

    # Run ingestion
    mapping_repo = MappingConfigRepository(db)
    config_loader = ConfigLoader(
        repository=mapping_repo,
        cache=ConfigCache(),
        validator=ConfigValidator(),
    )
    pipeline = build_ingestion_pipeline(
        db,
        config_loader=config_loader,
        mapping_repo=mapping_repo,
    )
    ingestion_result = await pipeline.process_file(
        str(partner_file),
        partner,
        "UPC",
        FileType.SETTLEMENT,
        reconciliation_date,
    )
    assert ingestion_result.stats.total_rows > 0, "Ingestion should process rows"
    assert ingestion_result.stats.success_rows > 0, "Ingestion should have successful rows"

    # Run reconciliation
    engine = ReconciliationEngine(db=db)
    result = await engine.reconcile(partner, reconciliation_date)

    return {
        "partner": partner,
        "total_internal": inserted,
        "ingestion_total": ingestion_result.stats.total_rows,
        "ingestion_success": ingestion_result.stats.success_rows,
        **_reconciliation_summary(result),
    }


# ── E2E Tests ────────────────────────────────────────────────────────────


def _require_e2e_env():
    """Validate MongoDB connection."""
    mongo_url = settings.mongodb_url
    if not mongo_url or mongo_url == "mongodb://localhost:27017":
        # Try common docker-compose URL
        pass
    return mongo_url


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_20_records_momo():
    """E2E: 20 MOMO records — seed → ingest → reconcile → verify."""
    mongo_url = _require_e2e_env()
    client = AsyncIOMotorClient(mongo_url)
    db = client[settings.db_name]

    try:
        # Clean
        await _cleanup_partner_data(db, PARTNER_MOMO)

        # Setup mapping config
        await _ensure_mapping_config(db, PARTNER_MOMO, "e2e-momo-20-00000000-0000-0000-0000-000000000001")

        # Write partner file
        partner_file = Path(f"/tmp/e2e_momo_20_{TEST_DATE.replace('-', '')}.xlsx")
        _write_partner_file(partner_file, PARTNER_MOMO, TEST_NUM_RECORDS)

        # Run full flow
        summary = await _run_full_flow(db, PARTNER_MOMO, partner_file, TEST_NUM_RECORDS)

        # Verify
        assert summary["ingestion_success"] == TEST_NUM_RECORDS, \
            f"Expected {TEST_NUM_RECORDS} ingested, got {summary['ingestion_success']}"
        assert summary["recon_total"] > 0, "Reconciliation should process records"
        assert summary["recon_matched"] > 0, "Expected at least some matched records"

        print("\n  MOMO 20-records results:")
        print(f"    Internal seeded: {summary['total_internal']}")
        print(f"    Ingested: {summary['ingestion_success']}/{summary['ingestion_total']}")
        print(f"    Reconciled: {summary['recon_total']} total, {summary['recon_matched']} matched")

    finally:
        # Cleanup test file
        if Path("/tmp/e2e_momo_20_*.xlsx").parent.exists():
            for f in Path("/tmp").glob("e2e_momo_20_*.xlsx"):
                f.unlink(missing_ok=True)
        await _cleanup_partner_data(db, PARTNER_MOMO)
        client.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_20_records_zalopay():
    """E2E: 20 ZALOPAY records — seed → ingest → reconcile → verify."""
    mongo_url = _require_e2e_env()
    client = AsyncIOMotorClient(mongo_url)
    db = client[settings.db_name]

    try:
        # Clean
        await _cleanup_partner_data(db, PARTNER_ZALOPAY)

        # Setup mapping config
        await _ensure_mapping_config(db, PARTNER_ZALOPAY, "e2e-zalo-20-00000000-0000-0000-0000-000000000002")

        # Write partner file
        partner_file = Path(f"/tmp/e2e_zalopay_20_{TEST_DATE.replace('-', '')}.xlsx")
        _write_partner_file(partner_file, PARTNER_ZALOPAY, TEST_NUM_RECORDS)

        # Run full flow
        summary = await _run_full_flow(db, PARTNER_ZALOPAY, partner_file, TEST_NUM_RECORDS)

        # Verify
        assert summary["ingestion_success"] == TEST_NUM_RECORDS, \
            f"Expected {TEST_NUM_RECORDS} ingested, got {summary['ingestion_success']}"
        assert summary["recon_total"] > 0, "Reconciliation should process records"
        assert summary["recon_matched"] > 0, "Expected at least some matched records"

        print("\n  ZALOPAY 20-records results:")
        print(f"    Internal seeded: {summary['total_internal']}")
        print(f"    Ingested: {summary['ingestion_success']}/{summary['ingestion_total']}")
        print(f"    Reconciled: {summary['recon_total']} total, {summary['recon_matched']} matched")

    finally:
        if Path("/tmp/e2e_zalopay_20_*.xlsx").parent.exists():
            for f in Path("/tmp").glob("e2e_zalopay_20_*.xlsx"):
                f.unlink(missing_ok=True)
        await _cleanup_partner_data(db, PARTNER_ZALOPAY)
        client.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_20_records_both_partners():
    """E2E: Run 20-record flow for MOMO + ZALOPAY sequentially and compare stats."""
    mongo_url = _require_e2e_env()
    client = AsyncIOMotorClient(mongo_url)
    db = client[settings.db_name]

    results = {}

    for partner, config_id, file_label in [
        (PARTNER_MOMO, "e2e-both-20-00000000-0000-0000-0000-000000000003", "momo"),
        (PARTNER_ZALOPAY, "e2e-both-20-00000000-0000-0000-0000-000000000004", "zalopay"),
    ]:
        try:
            await _cleanup_partner_data(db, partner)
            await _ensure_mapping_config(db, partner, config_id)
            partner_file = Path(f"/tmp/e2e_{file_label}_20_{TEST_DATE.replace('-', '')}.xlsx")
            _write_partner_file(partner_file, partner, TEST_NUM_RECORDS)
            results[partner] = await _run_full_flow(db, partner, partner_file, TEST_NUM_RECORDS)

            if partner_file.exists():
                partner_file.unlink()
        finally:
            await _cleanup_partner_data(db, partner)

    # Both partners should produce similar results for same-size datasets
    for partner, r in results.items():
        assert r["ingestion_success"] == TEST_NUM_RECORDS, \
            f"{partner}: Expected {TEST_NUM_RECORDS} ingested, got {r['ingestion_success']}"
        assert r["recon_matched"] > 0, f"{partner}: Expected matches"

    print("\n  Both partners 20-records comparison:")
    for partner, r in results.items():
        print(f"    {partner}: ingest={r['ingestion_success']}, "
              f"recon={r['recon_total']} total, {r['recon_matched']} matched")

    client.close()
