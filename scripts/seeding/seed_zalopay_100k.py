"""ZALOPAY 100k records seeding script.

Generates 100,000 internal transactions and writes a multi-column partner excel
file named `zalopay_YYYYMMDD.xlsx` (no "settlement_" prefix) to `sftp_data/`.
Optimized for RAM efficiency during Excel generation using openpyxl's write-only mode.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import openpyxl
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
    logger.info(f"Generating Excel file with {count} records at {path}...")
    date_str = _date_str(day)
    
    # Use write_only=True for extremely low memory footprint with 100k rows
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet()
    
    # 6 Blank rows for offset header matching ingestion configuration
    for _ in range(6):
        ws.append([])

    # 40 columns header
    headers = [""] * TOTAL_COLUMNS
    headers[0] = "STT"
    headers[1] = "zpTransId"
    headers[4] = "zpTotalAmount"
    headers[7] = "zpNgayGd"
    headers[10] = "zpMaHDon"
    headers[17] = "zpTrangThai"
    # Extra columns for "more columns than usual"
    headers[20] = "zpFeeAmount"
    headers[25] = "zpChannel"
    headers[30] = "zpAppId"
    headers[35] = "zpPromotionCode"
    headers[39] = "zpChecksum"
    ws.append(headers)

    for i in range(1, count + 1):
        txn_id = f"ZALO_TXN_80{i:06d}"
        amount = Decimal(50000 + (i % 10) * 10000)
        
        # Introduce a few discrepancies (e.g. 2 records with mismatch amounts)
        if i == 500 or i == 99999:
            amount += Decimal("5000") # Discrepancy
            
        row = [""] * TOTAL_COLUMNS
        row[0] = str(i)
        row[1] = txn_id
        row[4] = str(amount)
        row[7] = f"{date_str} 14:00:00"
        row[10] = f"BILL_ZP_{i:06d}"
        row[17] = "Thành công"
        row[20] = "1100"  # Fee
        row[25] = "DOMESTIC_CARD"
        row[30] = "APP_ZALO_PAY_1"
        row[35] = "PROMO_5K" if i % 5 == 0 else ""
        row[39] = f"md5_hash_{i}"
        ws.append(row)

    wb.save(path)
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
            { "path": "trace", "column": 11, "type": "STRING" },
            { "path": "amount", "column": 5, "type": "DECIMAL" },
            { "path": "currency", "constant": "VND", "type": "CONSTANT" },
            { "path": "status", "column": 18, "type": "MAPPING", "mapping": { "Thành công": "SUCCESS", "others": "FAILED" } },
            { "path": "transDate", "column": 8, "type": "DATE" },
            { "path": "extra.service", "constant": "PAYMENT", "type": "CONSTANT" },
            { "path": "extra.portal", "constant": "PaymentGateway", "type": "CONSTANT" },
            { "path": "extra.provider", "constant": "ZALOPAY", "type": "CONSTANT" }
        ],
        "configVersion": "v_template",
        "status": MappingConfigStatus.APPROVED.value,
        "createdAt": datetime.now(timezone.utc),
        "approvedAt": datetime.now(timezone.utc),
        "approvedBy": "admin"
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
    
    # Insert in batches of 10k to prevent driver timeout / out of memory
    batch_size = 10000
    batch = []
    now = datetime.now(timezone.utc)
    
    for i in range(1, count + 1):
        txn_id = f"ZALO_TXN_80{i:06d}"
        amount = Decimal(50000 + (i % 10) * 10000)
        
        doc = {
            "_id": f"INT_{PARTNER}_{txn_id}",
            "partner": PARTNER,
            "partnerTxnId": txn_id,
            "amount": Decimal128(str(amount)),
            "currency": "VND",
            "status": TransactionStatus.SUCCESS.value,
            "transactionTime": day,
            "createdAt": now,
            "updatedAt": now,
        }
        batch.append(doc)
        
        if len(batch) >= batch_size:
            await collection.insert_many(batch)
            logger.info(f"Inserted batch: {i}/{count}")
            batch = []
            
    if batch:
        await collection.insert_many(batch)
        logger.info(f"Inserted final batch: {count}/{count}")

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
        
        # Seed configs
        await _ensure_mapping_config(db)
        await _ensure_fetch_config(db)
        
        # Seed database
        await _seed_internal(db, day, NUM_RECORDS)
        logger.info("ZALOPAY reset completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())
