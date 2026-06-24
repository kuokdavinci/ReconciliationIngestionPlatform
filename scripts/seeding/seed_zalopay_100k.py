"""ZALOPAY 100k records seeding script.

Generates 100,000 internal transactions and writes a multi-column partner excel
file named `zalopay_YYYYMMDD.xlsx` (no "settlement_" prefix) to `sftp_data/`.
Optimized for RAM efficiency during Excel generation using openpyxl's write-only mode.
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import xlsxwriter
from bson.decimal128 import Decimal128
from motor.motor_asyncio import AsyncIOMotorClient

from src.config.settings import settings
from src.core.enums import TransactionStatus
from src.models.fetch_config import (
    FetchConfig,
    FetchConfigRepository,
    FetchMethod,
    FileDropConfig,
)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PARTNER = "ZALOPAY"
NUM_RECORDS = 100000
TOTAL_COLUMNS = 40  # More columns than MOMO's 30
MISSING_PARTNER_INDICES = {20000, 40000, 60000}
AMOUNT_MISMATCH_INDICES = {500, 25000, 75000, 99999}

def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

def _date_str(day: datetime) -> str:
    return day.strftime("%Y-%m-%d")

def _partner_file_path_for_day(day: datetime) -> Path:
    sftp_dir = Path("./sftp_data")
    sftp_dir.mkdir(exist_ok=True)
    # Remove older ZALOPAY files to avoid debris
    for old_file in sftp_dir.glob("zalopay_*.xlsx"):
        old_file.unlink()
    date_compact = _date_str(day).replace("-", "")
    # Filename without "settlement_" prefix as requested
    return sftp_dir / f"zalopay_{date_compact}.xlsx"

def _write_partner_file(path: Path, day: datetime, count: int):
    logger.info(f"Generating Excel file with {count} records at {path} using xlsxwriter...")
    date_str = _date_str(day)
    
    workbook = xlsxwriter.Workbook(str(path), {'constant_memory': True})
    worksheet = workbook.add_worksheet("Sheet1")
    
    # Write headers at row 6 (0-indexed, corresponding to row 7 in 1-indexed)
    worksheet.write(6, 0, "STT")
    worksheet.write(6, 1, "zpTransId")
    worksheet.write(6, 4, "zpTotalAmount")
    worksheet.write(6, 7, "zpNgayGd")
    worksheet.write(6, 10, "zpMaHDon")
    worksheet.write(6, 17, "zpTrangThai")
    worksheet.write(6, 20, "zpFeeAmount")
    worksheet.write(6, 25, "zpChannel")
    worksheet.write(6, 30, "zpAppId")
    worksheet.write(6, 35, "zpPromotionCode")
    worksheet.write(6, 39, "zpChecksum")

    row_idx = 7
    logger.info(
        "ZALOPAY 100k fixture: internal=%s, partner_rows=%s, missing_partner=%s, amount_mismatch=%s",
        count,
        count - len(MISSING_PARTNER_INDICES),
        len(MISSING_PARTNER_INDICES),
        len(AMOUNT_MISMATCH_INDICES),
    )
    
    for i in range(1, count + 1):
        if i in MISSING_PARTNER_INDICES:
            continue

        txn_id = f"ZALO_TXN_80{i:06d}"
        amount = Decimal(50000 + (i % 10) * 10000)
        
        if i in AMOUNT_MISMATCH_INDICES:
            amount += Decimal("5000")
            
        worksheet.write(row_idx, 0, str(i))
        worksheet.write(row_idx, 1, txn_id)
        worksheet.write(row_idx, 4, str(amount))
        worksheet.write(row_idx, 7, f"{date_str} 14:00:00")
        worksheet.write(row_idx, 10, f"BILL_ZP_{i:06d}")
        worksheet.write(row_idx, 17, "Thành công")
        worksheet.write(row_idx, 20, "1100")
        worksheet.write(row_idx, 25, "DOMESTIC_CARD")
        worksheet.write(row_idx, 30, "APP_ZALO_PAY_1")
        if i % 5 == 0:
            worksheet.write(row_idx, 35, "PROMO_5K")
        worksheet.write(row_idx, 39, f"md5_hash_{i}")
        row_idx += 1

    workbook.close()
    logger.info("Excel file generated successfully.")

async def _ensure_mapping_config(db) -> None:
    from src.models.mapping_config import MappingConfigStatus
    from src.core.enums import FileType
    collection = db["reconciliation_mapping_config"]
    await collection.delete_many({"$or": [{"partner": PARTNER}, {"_id": "88888888-8888-8888-8888-888888888888"}]})

    config_doc = {
        "_id": "88888888-8888-8888-8888-888888888888",
        "partner": PARTNER,
        "workflowType": "UPC",
        "fileType": FileType.SETTLEMENT.value,
        "sheetName": "Sheet1",
        "startRow": 8,
        "fieldMappings": [
            { "path": "id", "column": 2, "type": "STRING", "required": True },
            { "path": "extra.zpMaHDon", "column": 11, "type": "STRING" },
            { "path": "amount", "column": 5, "type": "DECIMAL" },
            { "path": "currency", "constant": "VND", "type": "CONSTANT" },
            { "path": "status", "column": 18, "type": "MAPPING", "mapping": { "Thành công": "SUCCESS", "others": "FAILED" } },
            { "path": "transDate", "column": 8, "type": "DATE" },
            { "path": "extra.service", "constant": "PAYMENT", "type": "CONSTANT" },
            { "path": "extra.portal", "constant": "PaymentGateway", "type": "CONSTANT" },
            { "path": "extra.provider", "constant": "ZALOPAY", "type": "CONSTANT" }
        ],
        "configVersion": "v_template",
        "status": MappingConfigStatus.PENDING_APPROVAL.value,
        "createdAt": datetime.now(timezone.utc)
    }
    await collection.insert_one(config_doc)

async def _ensure_fetch_config(db) -> None:
    repo = FetchConfigRepository(db)
    existing = await repo.find_by_partner(PARTNER)
    if existing is not None:
        await repo.delete_by_partner(PARTNER)

    fetch_config = FetchConfig(
        partner=PARTNER,
        fetchMethod=FetchMethod.FILEDROP,
        enabled=True,
        schedule="0 0 * * *",
        localDownloadDir="./downloads",
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(directory="./sftp_data", pattern="zalopay_*.xlsx"),
    )
    await repo.create(fetch_config)

async def _seed_internal(db, day: datetime, count: int):
    logger.info(f"Seeding {count} internal transactions to database...")
    collection = db["internal_transaction"]
    
    # Clean previous ZALOPAY data
    await collection.delete_many({"partner": PARTNER})
    
    # Generate all documents in memory first (extremely fast in Python)
    docs = []
    now = datetime.now(timezone.utc)
    
    for i in range(1, count + 1):
        txn_id = f"ZALO_TXN_80{i:06d}"

        amount = Decimal(50000 + (i % 10) * 10000)
        
        docs.append({
            "_id": f"INT_{PARTNER}_{txn_id}",
            "partner": PARTNER,
            "partnerTxnId": txn_id,
            "amount": Decimal128(str(amount)),
            "currency": "VND",
            "status": TransactionStatus.SUCCESS.value,
            "transactionTime": day,
            "createdAt": now,
            "updatedAt": now,
        })
        
    # Insert everything in one single MongoDB call (Zero TCP roundtrip overhead)
    await collection.insert_many(docs, ordered=False)
    logger.info(f"Inserted all {len(docs)} internal transactions successfully.")

async def _cleanup_existing_run_data(db) -> None:
    logger.info("Cleaning up existing ZALOPAY execution data...")
    collections_to_clean = [
        "review_packet",
        "reconciliation_file",
        "data_container",
        "reconciliation_result",
        "partner_runtime_run",
        "post_approval_run"
    ]
    for coll_name in collections_to_clean:
        query = {"identify": PARTNER} if coll_name == "data_container" else {"partner": PARTNER}
        res = await db[coll_name].delete_many(query)
        logger.info(f"Deleted {res.deleted_count} records from collection '{coll_name}'")

async def main():
    parser = argparse.ArgumentParser(description="Seed ZALOPAY 100k data")
    parser.add_argument("mode", choices=["reset"], help="Seeding action (only reset supported)")
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    day = _today_utc()

    if args.mode == "reset":
        # Generate file
        path = _partner_file_path_for_day(day)
        _write_partner_file(path, day, NUM_RECORDS)
        
        # Cleanup old runs
        await _cleanup_existing_run_data(db)
        
        # Seed configs
        await _ensure_mapping_config(db)
        await _ensure_fetch_config(db)
        
        # Seed database
        await _seed_internal(db, day, NUM_RECORDS)
        logger.info("ZALOPAY reset completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())
