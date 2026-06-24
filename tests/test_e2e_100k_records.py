"""E2E test: 100k records ingestion + reconciliation for MOMO and ZALOPAY.

Large-volume verification of the full pipeline:
1. Seed 100k internal transactions + partner file for each partner
2. Run IngestionPipeline.process_file() with configurable batch sizes
3. Run ReconciliationEngine.reconcile() in fast_mode
4. Verify reconciliation results and performance characteristics

Requires:
- Running MongoDB + PostgreSQL (docker compose up)
- Sufficient disk/memory for 100k records
- --e2e flag: pytest tests/test_e2e_100k_records.py -v --e2e
"""

import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import xlsxwriter
import pytest
from bson.decimal128 import Decimal128
from motor.motor_asyncio import AsyncIOMotorClient
from src.config.settings import settings

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.models.mapping_config import MappingConfigRepository
from src.pipeline.ingestion_pipeline import IngestionPipeline
from src.reconciliation.engine import ReconciliationEngine


# ── Constants ────────────────────────────────────────────────────────────

PARTNER_MOMO = "MOMO"
PARTNER_ZALOPAY = "ZALOPAY"
TEST_DATE = "2026-06-24"
NUM_RECORDS = 100000

# For ZALOPAY: simulate some real-world mismatches
ZALO_MISSING_PARTNER_INDICES = {20000, 40000, 60000}
ZALO_AMOUNT_MISMATCH_INDICES = {500, 25000, 75000, 99999}


# ── Helpers ──────────────────────────────────────────────────────────────


def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


async def _ensure_mapping_config(db, partner: str, config_id: str) -> None:
    """Ensure an APPROVED mapping config exists."""
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
        "configVersion": "v_e2e_100k",
        "status": "APPROVED",
        "approvedAt": datetime.now(timezone.utc),
        "approvedBy": "e2e_test",
        "createdAt": datetime.now(timezone.utc),
    }
    await collection.insert_one(doc)


def _write_momo_partner_file(path: Path, count: int) -> None:
    """Write MOMO partner xlsx with `count` rows using xlsxwriter (fast)."""
    workbook = xlsxwriter.Workbook(str(path), {"constant_memory": True})
    worksheet = workbook.add_worksheet("Sheet1")

    # 6 blank rows + header at row 7
    worksheet.write(6, 0, "STT")
    worksheet.write(6, 1, "msTransId")
    worksheet.write(6, 4, "msTotalAmount")
    worksheet.write(6, 7, "msNgayHoanThanh")
    worksheet.write(6, 10, "msMaHDon")
    worksheet.write(6, 17, "msTrangThaiGd")

    row_idx = 7
    for i in range(1, count + 1):
        txn_id = f"MOMO_E2E_{i:06d}"
        amount = 50000 + (i % 10) * 10000
        worksheet.write(row_idx, 0, str(i))
        worksheet.write(row_idx, 1, txn_id)
        worksheet.write(row_idx, 4, str(amount))
        worksheet.write(row_idx, 7, f"{TEST_DATE} 12:00:00")
        worksheet.write(row_idx, 10, txn_id)
        worksheet.write(row_idx, 17, "Thành công")
        row_idx += 1

    workbook.close()


def _write_zalopay_partner_file(path: Path, count: int) -> None:
    """Write ZALOPAY partner xlsx with `count` rows (with intentional mismatches)."""
    workbook = xlsxwriter.Workbook(str(path), {"constant_memory": True})
    worksheet = workbook.add_worksheet("Sheet1")

    worksheet.write(6, 0, "STT")
    worksheet.write(6, 1, "zpTransId")
    worksheet.write(6, 4, "zpTotalAmount")
    worksheet.write(6, 7, "zpNgayGd")
    worksheet.write(6, 10, "zpMaHDon")
    worksheet.write(6, 17, "zpTrangThai")

    row_idx = 7
    for i in range(1, count + 1):
        # Skip missing-partner records (these exist in internal but not in partner file)
        if i in ZALO_MISSING_PARTNER_INDICES:
            continue

        txn_id = f"ZALO_E2E_{i:06d}"
        amount = 50000 + (i % 10) * 10000
        if i in ZALO_AMOUNT_MISMATCH_INDICES:
            amount += 5000

        worksheet.write(row_idx, 0, str(i))
        worksheet.write(row_idx, 1, txn_id)
        worksheet.write(row_idx, 4, str(amount))
        worksheet.write(row_idx, 7, f"{TEST_DATE} 14:00:00")
        worksheet.write(row_idx, 10, f"BILL_ZP_{i:06d}")
        worksheet.write(row_idx, 17, "Thành công")
        row_idx += 1

    workbook.close()


async def _seed_internal_momo(db, count: int) -> int:
    """Bulk seed MOMO internal transactions."""
    collection = db["internal_transaction"]
    await collection.delete_many({"partner": PARTNER_MOMO})
    now = datetime.now(timezone.utc)
    day = _today_utc()
    docs = []
    for i in range(1, count + 1):
        txn_id = f"MOMO_E2E_{i:06d}"
        amount = Decimal(50000 + (i % 10) * 10000)
        docs.append({
            "_id": f"INT_{PARTNER_MOMO}_{txn_id}",
            "partner": PARTNER_MOMO,
            "partnerTxnId": txn_id,
            "amount": Decimal128(str(amount)),
            "currency": "VND",
            "status": "SUCCESS",
            "transactionTime": day,
            "createdAt": now,
            "updatedAt": now,
        })
    await collection.insert_many(docs, ordered=False)
    return len(docs)


async def _seed_internal_zalopay(db, count: int) -> int:
    """Bulk seed ZALOPAY internal transactions with intentional mismatches."""
    collection = db["internal_transaction"]
    await collection.delete_many({"partner": PARTNER_ZALOPAY})
    now = datetime.now(timezone.utc)
    day = _today_utc()
    docs = []
    for i in range(1, count + 1):
        txn_id = f"ZALO_E2E_{i:06d}"
        amount = Decimal(50000 + (i % 10) * 10000)
        if i in ZALO_AMOUNT_MISMATCH_INDICES:
            amount += Decimal("5000")
        docs.append({
            "_id": f"INT_{PARTNER_ZALOPAY}_{txn_id}",
            "partner": PARTNER_ZALOPAY,
            "partnerTxnId": txn_id,
            "amount": Decimal128(str(amount)),
            "currency": "VND",
            "status": "SUCCESS",
            "transactionTime": day,
            "createdAt": now,
            "updatedAt": now,
        })
    await collection.insert_many(docs, ordered=False)
    return len(docs)


async def _cleanup_partner_data(db, partner: str) -> None:
    """Clean up all data for a partner."""
    for coll_name in [
        "reconciliation_result", "reconciliation_file", "data_container",
        "review_packet", "reconciliation_mapping_config", "internal_transaction",
        "partner_runtime_run", "post_approval_run", "reconciliation_review_record",
    ]:
        query = {"identify": partner} if coll_name == "data_container" else {"partner": partner}
        try:
            await db[coll_name].delete_many(query)
        except Exception:
            pass


async def _run_100k_flow(
    db, partner: str, partner_file: Path,
    seed_fn, expected_partner_rows: int, expected_internal: int
) -> dict:
    """Run seed → ingestion → reconciliation for large volume, measure timing."""
    timings = {}

    # Seed
    t0 = time.monotonic()
    inserted = await seed_fn(db, expected_internal)
    t1 = time.monotonic()
    timings["seed_seconds"] = round(t1 - t0, 3)

    # Run ingestion with optimized batch sizes
    config_loader = ConfigLoader(
        db=db,
        repo=MappingConfigRepository(db),
        cache=ConfigCache(),
        validator=ConfigValidator(),
    )
    pipeline = IngestionPipeline(
        db=db,
        config_loader=config_loader,
        batch_size=20000,
        write_workers=2,
        ordered_insert=False,
    )
    t0 = time.monotonic()
    ingestion_result = await pipeline.process_file(str(partner_file), partner, TEST_DATE)
    t1 = time.monotonic()
    timings["ingest_seconds"] = round(t1 - t0, 3)

    # Run reconciliation with optimized settings
    engine = ReconciliationEngine(
        db=db,
        fast_mode=True,
        result_batch_size=20000,
        write_workers=2,
        ordered_insert=False,
    )
    t0 = time.monotonic()
    result = await engine.reconcile(partner, TEST_DATE)
    t1 = time.monotonic()
    timings["recon_seconds"] = round(t1 - t0, 3)

    total_seconds = timings["seed_seconds"] + timings["ingest_seconds"] + timings["recon_seconds"]

    return {
        "partner": partner,
        "total_internal": inserted,
        "expected_partner_rows": expected_partner_rows,
        "ingestion_total": ingestion_result.stats.total_rows,
        "ingestion_success": ingestion_result.stats.success_rows,
        "ingestion_errors": ingestion_result.stats.error_rows or 0,
        "recon_total": result.get("total_processed", 0),
        "recon_matched": result.get("matched", 0),
        "recon_amount_mismatch": result.get("amount_mismatch", 0),
        "recon_missing_internal": result.get("missing_internal", 0),
        "recon_missing_partner": result.get("missing_partner", 0),
        "timing_seconds": timings,
        "total_seconds": round(total_seconds, 3),
        "records_per_sec_ingest": round(expected_partner_rows / timings["ingest_seconds"], 1) if timings["ingest_seconds"] > 0 else 0,
        "records_per_sec_recon": round(expected_internal / timings["recon_seconds"], 1) if timings["recon_seconds"] > 0 else 0,
    }


# ── E2E Tests ────────────────────────────────────────────────────────────


def _require_e2e_env():
    return settings.mongodb_url


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_100k_momo():
    """E2E: 100k MOMO records — large volume ingestion + reconciliation."""
    mongo_url = _require_e2e_env()
    client = AsyncIOMotorClient(mongo_url)
    db = client[settings.db_name]

    try:
        await _cleanup_partner_data(db, PARTNER_MOMO)
        await _ensure_mapping_config(db, PARTNER_MOMO, "e2e-momo-100k-00000000-0000-0000-0000-000000000010")

        partner_file = Path(f"/tmp/e2e_momo_100k_{TEST_DATE.replace('-', '')}.xlsx")
        _write_momo_partner_file(partner_file, NUM_RECORDS)

        summary = await _run_100k_flow(
            db, PARTNER_MOMO, partner_file,
            seed_fn=lambda db, c: _seed_internal_momo(db, NUM_RECORDS),
            expected_partner_rows=NUM_RECORDS,
            expected_internal=NUM_RECORDS,
        )

        # MOMO: all 100k should match (no intentional mismatches)
        assert summary["ingestion_success"] == NUM_RECORDS, \
            f"Expected {NUM_RECORDS} ingested, got {summary['ingestion_success']}"
        assert summary["recon_matched"] > 0, "Expected matches"
        assert summary["records_per_sec_ingest"] > 1000, \
            f"Ingestion too slow: {summary['records_per_sec_ingest']} rec/s"

        print("\n  MOMO 100k performance:")
        print(f"    Seed: {summary['timing_seconds']['seed_seconds']}s")
        print(f"    Ingest: {summary['timing_seconds']['ingest_seconds']}s "
              f"({summary['records_per_sec_ingest']} rec/s)")
        print(f"    Recon: {summary['timing_seconds']['recon_seconds']}s "
              f"({summary['records_per_sec_recon']} rec/s)")
        print(f"    Total: {summary['total_seconds']}s")
        print(f"    Results: {summary['recon_total']} total, "
              f"{summary['recon_matched']} matched")

    finally:
        if Path("/tmp/e2e_momo_100k_*.xlsx").parent.exists():
            for f in Path("/tmp").glob("e2e_momo_100k_*.xlsx"):
                f.unlink(missing_ok=True)
        await _cleanup_partner_data(db, PARTNER_MOMO)
        client.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_100k_zalopay():
    """E2E: 100k ZALOPAY records — large volume with intentional mismatches."""
    mongo_url = _require_e2e_env()
    client = AsyncIOMotorClient(mongo_url)
    db = client[settings.db_name]

    expected_partner_rows = NUM_RECORDS - len(ZALO_MISSING_PARTNER_INDICES)

    try:
        await _cleanup_partner_data(db, PARTNER_ZALOPAY)
        await _ensure_mapping_config(db, PARTNER_ZALOPAY, "e2e-zalo-100k-00000000-0000-0000-0000-000000000011")

        partner_file = Path(f"/tmp/e2e_zalopay_100k_{TEST_DATE.replace('-', '')}.xlsx")
        _write_zalopay_partner_file(partner_file, NUM_RECORDS)

        summary = await _run_100k_flow(
            db, PARTNER_ZALOPAY, partner_file,
            seed_fn=lambda db, c: _seed_internal_zalopay(db, NUM_RECORDS),
            expected_partner_rows=expected_partner_rows,
            expected_internal=NUM_RECORDS,
        )

        # ZALOPAY has intentional mismatches
        assert summary["ingestion_success"] == expected_partner_rows, \
            f"Expected {expected_partner_rows} ingested (excluding missing partner), " \
            f"got {summary['ingestion_success']}"
        assert summary["recon_total"] > 0, "Reconciliation should process records"
        assert summary["recon_matched"] > 0, "Expected at least some matched records"
        assert summary["recon_missing_partner"] == len(ZALO_MISSING_PARTNER_INDICES), \
            f"Expected {len(ZALO_MISSING_PARTNER_INDICES)} missing partner, " \
            f"got {summary['recon_missing_partner']}"

        print("\n  ZALOPAY 100k performance:")
        print(f"    Seed: {summary['timing_seconds']['seed_seconds']}s")
        print(f"    Ingest: {summary['timing_seconds']['ingest_seconds']}s "
              f"({summary['records_per_sec_ingest']} rec/s)")
        print(f"    Recon: {summary['timing_seconds']['recon_seconds']}s "
              f"({summary['records_per_sec_recon']} rec/s)")
        print(f"    Total: {summary['total_seconds']}s")
        print(f"    Results: {summary['recon_total']} total, "
              f"{summary['recon_matched']} matched, "
              f"{summary['recon_missing_partner']} missing_partner")

    finally:
        if Path("/tmp/e2e_zalopay_100k_*.xlsx").parent.exists():
            for f in Path("/tmp").glob("e2e_zalopay_100k_*.xlsx"):
                f.unlink(missing_ok=True)
        await _cleanup_partner_data(db, PARTNER_ZALOPAY)
        client.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_100k_performance_comparison():
    """E2E: Compare MOMO vs ZALOPAY 100k performance characteristics.

    Verifies both partners can handle large volumes with acceptable throughput.
    """
    mongo_url = _require_e2e_env()
    client = AsyncIOMotorClient(mongo_url)
    db = client[settings.db_name]

    results = {}

    for partner, config_id, file_label, write_fn, seed_fn in [
        (
            PARTNER_MOMO, "e2e-perf-100k-00000000-0000-0000-0000-000000000012",
            "momo", _write_momo_partner_file,
            lambda db, c: _seed_internal_momo(db, NUM_RECORDS),
        ),
        (
            PARTNER_ZALOPAY, "e2e-perf-100k-00000000-0000-0000-0000-000000000013",
            "zalopay", _write_zalopay_partner_file,
            lambda db, c: _seed_internal_zalopay(db, NUM_RECORDS),
        ),
    ]:
        try:
            await _cleanup_partner_data(db, partner)
            await _ensure_mapping_config(db, partner, config_id)

            partner_file = Path(f"/tmp/e2e_{file_label}_100k_{TEST_DATE.replace('-', '')}.xlsx")
            write_fn(partner_file, NUM_RECORDS)

            expected_partner_rows = NUM_RECORDS
            if partner == PARTNER_ZALOPAY:
                expected_partner_rows = NUM_RECORDS - len(ZALO_MISSING_PARTNER_INDICES)

            s = await _run_100k_flow(
                db, partner, partner_file, seed_fn,
                expected_partner_rows=expected_partner_rows,
                expected_internal=NUM_RECORDS,
            )
            results[partner] = s

            if partner_file.exists():
                partner_file.unlink()
        finally:
            await _cleanup_partner_data(db, partner)

    # Both must pass basic thresholds
    for partner, s in results.items():
        assert s["ingestion_success"] > 0, f"{partner}: ingestion failed"
        assert s["records_per_sec_ingest"] > 1000, \
            f"{partner}: ingestion too slow ({s['records_per_sec_ingest']} rec/s)"
        assert s["records_per_sec_recon"] > 1000, \
            f"{partner}: reconciliation too slow ({s['records_per_sec_recon']} rec/s)"

    print("\n  100k Performance Comparison:")
    print(f"  {'Partner':<12} {'Ingest(s)':<12} {'Rec/s':<12} {'Recon(s)':<12} {'Rec/s':<12} {'Match':<10} {'Total(s)':<10}")
    print(f"  {'-'*68}")
    for partner, s in results.items():
        t = s["timing_seconds"]
        print(f"  {partner:<12} {t['ingest_seconds']:<12} {s['records_per_sec_ingest']:<12} "
              f"{t['recon_seconds']:<12} {s['records_per_sec_recon']:<12} "
              f"{s['recon_matched']:<10} {s['total_seconds']:<10}")

    client.close()
