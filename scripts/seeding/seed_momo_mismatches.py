"""Seed MOMO data with intentional mismatches for today."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import openpyxl
from bson.decimal128 import Decimal128
from motor.motor_asyncio import AsyncIOMotorClient

from src.config.settings import settings
from src.core.enums import TransactionStatus

PARTNER = "MOMO"

def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

def _date_str(day: datetime) -> str:
    return day.strftime("%Y-%m-%d")

async def main():
    day = _today_utc()
    date_compact = _date_str(day).replace("-", "")
    partner_file_path = Path(f"./sftp_data/settlement_MOMO_{date_compact}.xlsx")
    
    # 1. Clean existing files
    sftp_dir = Path("./sftp_data")
    sftp_dir.mkdir(exist_ok=True)
    for old_file in sftp_dir.glob("settlement_MOMO_*.xlsx"):
        old_file.unlink()

    # 2. Connect to MongoDB
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    
    # Clean database collections for MOMO and today
    await db["internal_transaction"].delete_many({"partner": PARTNER})
    await db["reconciliation_result"].delete_many({"partner": PARTNER})
    await db["review_packet"].delete_many({"partner": PARTNER})
    await db["reconciliation_file"].delete_many({"partner": PARTNER})
    await db["data_container"].delete_many({"identify": PARTNER})
    
    print(f"Cleaned MOMO database collections (internal_transaction, reconciliation_result, review_packet, reconciliation_file, data_container).")

    # 3. Define transactions
    now = datetime.now(timezone.utc)
    
    # Normal matched transactions
    matched_keys = [f"MOMO_TXN_MATCH_{i:02d}" for i in range(10)]
    internal_docs = []
    partner_rows = []
    
    # Seed matched transactions
    for i, txn_id in enumerate(matched_keys):
        amount = Decimal("100000")
        internal_docs.append({
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
        partner_rows.append((txn_id, amount))

    # Seed Amount Mismatch transaction
    mismatch_txn = "MOMO_TXN_AMT_MISMATCH"
    internal_docs.append({
        "_id": f"INT_{PARTNER}_{mismatch_txn}",
        "partner": PARTNER,
        "partnerTxnId": mismatch_txn,
        "amount": Decimal128("100000"), # 100K VND internal
        "currency": "VND",
        "status": TransactionStatus.SUCCESS.value,
        "transactionTime": day,
        "createdAt": now,
        "updatedAt": now,
    })
    partner_rows.append((mismatch_txn, Decimal("120000"))) # 120K VND partner

    # Seed Missing Partner transaction (present in internal, absent from partner file)
    missing_partner_txn = "MOMO_TXN_MISSING_PARTNER"
    internal_docs.append({
        "_id": f"INT_{PARTNER}_{missing_partner_txn}",
        "partner": PARTNER,
        "partnerTxnId": missing_partner_txn,
        "amount": Decimal128("150000"),
        "currency": "VND",
        "status": TransactionStatus.SUCCESS.value,
        "transactionTime": day,
        "createdAt": now,
        "updatedAt": now,
    })
    # Do not add to partner_rows

    # Seed Missing Internal transaction (absent from internal, present in partner file)
    missing_internal_txn = "MOMO_TXN_MISSING_INTERNAL"
    partner_rows.append((missing_internal_txn, Decimal("200000")))
    # Do not add to internal_docs

    # Insert internal transactions into MongoDB
    if internal_docs:
        await db["internal_transaction"].insert_many(internal_docs)
        print(f"Seeded {len(internal_docs)} internal transactions.")

    # 4. Generate MOMO Partner XLSX File
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # 6 blank rows
    for _ in range(6):
        ws.append([])

    # Row 7 is Header
    headers = [""] * 30
    headers[0] = "STT"
    headers[1] = "msTransId"
    headers[4] = "msTotalAmount"
    headers[7] = "msNgayHoanThanh"
    headers[10] = "msMaHDon"
    headers[17] = "msTrangThaiGd"
    ws.append(headers)

    # Data Rows
    date_str = _date_str(day)
    for index, (txn_id, amount) in enumerate(partner_rows, start=1):
        row = [""] * 30
        row[0] = str(index)
        row[1] = txn_id
        row[4] = str(amount)
        row[7] = f"{date_str} 12:00:00"
        row[10] = txn_id
        row[17] = "Thành công"
        ws.append(row)

    wb.save(partner_file_path)
    print(f"Generated partner file with {len(partner_rows)} rows at {partner_file_path}")
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
