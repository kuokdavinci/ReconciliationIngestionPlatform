"""Seed MongoDB with realistic transaction data for pipeline testing.

Generates thousands of MOMO/VNPAY/ZALOPAY records across all collections
so the pipeline, reconciliation, and AI insights have real data to work with.

Usage:
    uv run python seed_db.py              # seed default (500 MOMO records)
    uv run python seed_db.py --count 5000  # seed 5000 MOMO records
    uv run python seed_db.py --clear       # clear all seeded data first
"""

import asyncio
import argparse
import random
import uuid as _uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from motor.motor_asyncio import AsyncIOMotorClient

from bson import Decimal128

from src.config.settings import settings
from src.models.data_container import DataContainer, PartnerData
from src.models.internal_transaction import InternalTransaction
from src.models.reconciliation_result import ReconciliationResult
from src.models.reconciliation_file import ReconciliationFile
from src.core.enums import FileType, ProcessingStatus, ReconciliationStatus

# --- constants ---
PARTNERS = ["MOMO", "VNPAY", "ZALOPAY"]
SERVICES = ["PAYMENT", "TRANSFER", "BILL_PAY", "TOPUP", "WITHDRAWAL"]
PORTALS = ["PaymentGateway", "MobileApp", "WebPortal", "QRCode", "BankTransfer"]
STATUSES = ["SUCCESS", "FAILED", "REFUNDED", "PENDING"]
RECON_DATE = datetime(2024, 7, 7, tzinfo=timezone.utc)
BASE_DATE = RECON_DATE - timedelta(days=2)

SEED_TAG = "seed_db"  # used to identify seed-generated records


def _random_amount():
    amounts = [50000, 100000, 150000, 200000, 259200, 300000, 500000, 831800, 1000000, 2500000, 5000000]
    return Decimal(str(random.choice(amounts) + random.randint(0, 999)))


def _random_trace(partner, idx):
    prefix = {"MOMO": "240705", "VNPAY": "240706", "ZALOPAY": "240704"}[partner]
    return f"{prefix}{str(idx).zfill(19)}"


def _random_status():
    return random.choice(STATUSES)


def _random_trans_date():
    return BASE_DATE + timedelta(
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )


def _random_id():
    return str(_uuid.uuid4())


def _to_mongo(obj, by_alias=True):
    """Serialize a Pydantic model to a MongoDB-safe dict.

    Converts UUID -> str, Decimal -> Decimal128 for MongoDB compatibility.
    """
    d = obj.model_dump(by_alias=by_alias)
    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, Decimal):
            d[k] = Decimal128(v)
        elif isinstance(v, dict):
            _deep_convert(v)
    return d


def _deep_convert(d):
    for k, v in list(d.items()):
        if isinstance(v, Decimal):
            d[k] = Decimal128(v)
        elif isinstance(v, dict):
            _deep_convert(v)


def _generate_partner_data(partner, idx, status, amount, trace, trans_date):
    return PartnerData(
        _id=str(100000000 + idx),
        trace=trace,
        status=status,
        amount=amount,
        currency="VND",
        transDate=trans_date,
        extra={
            "service": random.choice(SERVICES),
            "portal": random.choice(PORTALS),
            "provider": partner,
        },
    )


def _generate_data_container(source_file_id, partner, idx, status, amount, trace, trans_date):
    return DataContainer(
        _id=_uuid.uuid4(),
        requestId=_uuid.uuid4(),
        identify=partner,
        workflowType="UPC",
        reconciliationDate=RECON_DATE,
        operationStatus="COMPLETED",
        reconciliationStatus="",
        sourceFileId=source_file_id,
        partnerData=_generate_partner_data(partner, idx, status, amount, trace, trans_date),
        createdBy=SEED_TAG,
    )


async def seed(args):
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]

    count = args.count
    clear = args.clear

    # --- clear mode ---
    if clear:
        for coll in ["data_container", "internal_transaction", "reconciliation_result", "reconciliation_file"]:
            result = await db[coll].delete_many({"createdBy": SEED_TAG})
            print(f"  Cleared {result.deleted_count} from {coll}")
        result = await db["reconciliation_file"].delete_many({"partner": {"$in": PARTNERS}})
        print(f"  Cleared {result.deleted_count} old reconciliation_file records")
        print("Done clearing.")
        return

    print(f"Seeding {count} records per core collection...\n")

    # --- 1. reconciliation_file ---
    file_records = []
    for partner in PARTNERS[:2]:  # MOMO, VNPAY
        rf = ReconciliationFile(
            partner=partner,
            fileName=f"settlement_{partner}_{RECON_DATE.strftime('%Y%m%d')}.xlsx",
            fileHash=_random_id(),
            fileType=FileType.SETTLEMENT,
            reconciliationDate=RECON_DATE,
            processingStatus=ProcessingStatus.COMPLETED,
            totalRows=count,
            successRows=int(count * 0.97),
            failedRows=int(count * 0.03),
            configVersion="v_template",
            createdBy=SEED_TAG,
        )
        file_records.append(rf)
    await db["reconciliation_file"].insert_many(
        [_to_mongo(rf) for rf in file_records]
    )
    print(f"  Inserted {len(file_records)} reconciliation_file records")

    # --- 2. data_container + internal_transaction + reconciliation_result ---
    all_data_containers = []
    all_internal_txns = []
    all_results = []
    matched_count = 0
    mismatch_count = 0
    missing_internal_count = 0
    missing_partner_count = 0

    for partner in PARTNERS[:2]:
        source_file_id = file_records[0].id if partner == "MOMO" else file_records[1].id
        total = count

        for i in range(total):
            status = _random_status()
            amount = _random_amount()
            trace = _random_trace(partner, i)
            trans_date = _random_trans_date()
            partner_data = DataContainer(
                _id=_uuid.uuid4(),
                requestId=_uuid.uuid4(),
                identify=partner,
                workflowType="UPC",
                reconciliationDate=RECON_DATE,
                operationStatus="COMPLETED",
                reconciliationStatus="",
                sourceFileId=source_file_id,
                partnerData=_generate_partner_data(partner, i, status, amount, trace, trans_date),
                createdBy=SEED_TAG,
            )
            all_data_containers.append(partner_data)

        # generate fewer internal transactions for realistic matching patterns
        internal_count = int(total * 0.85)
        internal_txns = []
        for i in range(internal_count):
            it = InternalTransaction(
                _id=f"int_{partner}_{i}",
                partner=partner,
                partnerTxnId=_random_trace(partner, i),
                amount=_random_amount(),
                currency="VND",
                status=random.choice(["SUCCESS", "SUCCESS", "SUCCESS", "FAILED"]),
                transactionTime=_random_trans_date(),
                createdAt=datetime.utcnow(),
                updatedAt=datetime.utcnow(),
            )
            internal_txns.append(it)
        all_internal_txns.extend(internal_txns)

        # reconciliation results: mix of MATCHED, AMOUNT_MISMATCH, MISSING_INTERNAL, MISSING_PARTNER
        matched = int(total * 0.78)
        amt_mismatch = int(total * 0.05)
        missing_int = int(total * 0.10)
        missing_ptnr = total - matched - amt_mismatch - missing_int

        partner_data_used = all_data_containers[-total:]

        for i in range(matched):
            txn_id = _random_trace(partner, i)
            amt = _random_amount()
            pid = str(partner_data_used[i].id)
            all_results.append(ReconciliationResult(
                _id=txn_id,
                partner=partner,
                date=RECON_DATE.strftime("%Y-%m-%d"),
                partnerTxnId=txn_id,
                internalTxnId=f"int_{partner}_{i}",
                partnerAmount=amt,
                internalAmount=amt,
                partnerStatus="SUCCESS",
                internalStatus="SUCCESS",
                reconciliationStatus=ReconciliationStatus.MATCHED,
                partnerRecordId=pid,
                internalRecordId=f"int_{partner}_{i}",
                createdAt=datetime.utcnow(),
            ))
            matched_count += 1

        for i in range(amt_mismatch):
            idx = matched + i
            txn_id = _random_trace(partner, idx)
            amt_p = _random_amount()
            amt_i = Decimal(str(int(amt_p) - random.randint(1000, 50000)))
            pid = str(partner_data_used[idx].id) if idx < len(partner_data_used) else _random_id()
            all_results.append(ReconciliationResult(
                _id=txn_id,
                partner=partner,
                date=RECON_DATE.strftime("%Y-%m-%d"),
                partnerTxnId=txn_id,
                internalTxnId=f"int_{partner}_{idx}",
                partnerAmount=amt_p,
                internalAmount=amt_i,
                partnerStatus="SUCCESS",
                internalStatus="SUCCESS",
                reconciliationStatus=ReconciliationStatus.AMOUNT_MISMATCH,
                partnerRecordId=pid,
                internalRecordId=f"int_{partner}_{idx}",
                createdAt=datetime.utcnow(),
            ))
            mismatch_count += 1

        for i in range(missing_int):
            idx = matched + amt_mismatch + i
            txn_id = _random_trace(partner, idx)
            amt = _random_amount()
            pid = str(partner_data_used[idx].id) if idx < len(partner_data_used) else _random_id()
            all_results.append(ReconciliationResult(
                _id=txn_id,
                partner=partner,
                date=RECON_DATE.strftime("%Y-%m-%d"),
                partnerTxnId=txn_id,
                internalTxnId=None,
                partnerAmount=amt,
                internalAmount=None,
                partnerStatus="SUCCESS",
                internalStatus=None,
                reconciliationStatus=ReconciliationStatus.MISSING_INTERNAL,
                partnerRecordId=pid,
                internalRecordId=None,
                createdAt=datetime.utcnow(),
            ))
            missing_internal_count += 1

        for i in range(missing_ptnr):
            idx = matched + amt_mismatch + missing_int + i
            txn_id = _random_trace(partner, idx)
            amt = _random_amount()
            pid = _random_id()
            all_results.append(ReconciliationResult(
                _id=txn_id,
                partner=partner,
                date=RECON_DATE.strftime("%Y-%m-%d"),
                partnerTxnId=txn_id,
                internalTxnId=f"int_missing_{partner}_{i}",
                partnerAmount=None,
                internalAmount=amt,
                partnerStatus=None,
                internalStatus="SUCCESS",
                reconciliationStatus=ReconciliationStatus.MISSING_PARTNER,
                partnerRecordId=pid,
                internalRecordId=f"int_missing_{partner}_{i}",
                createdAt=datetime.utcnow(),
            ))
            missing_partner_count += 1

    # batch insert data_container
    batch_size = 500
    for i in range(0, len(all_data_containers), batch_size):
        batch = all_data_containers[i:i + batch_size]
        await db["data_container"].insert_many(
            [_to_mongo(dc) for dc in batch]
        )
    print(f"  Inserted {len(all_data_containers)} data_container records (MOMO={count}, VNPAY={count})")

    # batch insert internal_transaction
    for i in range(0, len(all_internal_txns), batch_size):
        batch = all_internal_txns[i:i + batch_size]
        await db["internal_transaction"].insert_many(
            [_to_mongo(it) for it in batch]
        )
    print(f"  Inserted {len(all_internal_txns)} internal_transaction records")

    # batch insert reconciliation_result
    for i in range(0, len(all_results), batch_size):
        batch = all_results[i:i + batch_size]
        await db["reconciliation_result"].insert_many(
            [_to_mongo(rr) for rr in batch]
        )
    print(f"  Inserted {len(all_results)} reconciliation_result records")

    # --- summary ---
    print(f"\n--- Seed Summary ---")
    print(f"  MATCHED:          {matched_count}")
    print(f"  AMOUNT_MISMATCH:  {mismatch_count}")
    print(f"  MISSING_INTERNAL: {missing_internal_count}")
    print(f"  MISSING_PARTNER:  {missing_partner_count}")

    total_from_partner = count * 2
    matched_pct = (matched_count / total_from_partner) * 100
    mismatch_pct = (mismatch_count / total_from_partner) * 100
    missing_int_pct = (missing_internal_count / total_from_partner) * 100
    missing_ptnr_pct = (missing_partner_count / total_from_partner) * 100
    print(f"\n  MATCHED rate:      {matched_pct:.1f}%")
    print(f"  AMOUNT_MISMATCH:  {mismatch_pct:.1f}%")
    print(f"  MISSING_INTERNAL: {missing_int_pct:.1f}%")
    print(f"  MISSING_PARTNER:  {missing_ptnr_pct:.1f}%")
    print(f"\n  Total data_container:     {total_from_partner}")
    print(f"  Total internal_txn:     {len(all_internal_txns)}")
    print(f"  Total reconciliation:   {len(all_results)}")
    print("\n✅ Done. Run `uv run python run.py --reconcile 2024-07-07 --partner MOMO` to test reconciliation.")

    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed pipeline test data")
    parser.add_argument("--count", type=int, default=500, help="Number of records per partner (default: 500)")
    parser.add_argument("--clear", action="store_true", help="Clear all seed-generated data")
    args = parser.parse_args()
    asyncio.run(seed(args))
