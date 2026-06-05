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
from enum import Enum
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
STATUSES = ["SUCCESS", "FAILED", "REVERSED", "PENDING"]
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

    Converts UUID -> str, Decimal -> Decimal128, enum -> str.
    """
    d = obj.model_dump(by_alias=by_alias)
    _deep_convert(d)
    return d


def _deep_convert(d):
    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, Decimal):
            d[k] = Decimal128(v)
        elif isinstance(v, dict):
            _deep_convert(v)
        elif isinstance(v, Enum):
            d[k] = v.value


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

    # auto-clear previous seed data to avoid duplicate key errors
    clear_filters = {
        "data_container": {"createdBy": SEED_TAG},
        "internal_transaction": {},
        "reconciliation_result": {},
        "reconciliation_file": {"createdBy": SEED_TAG},
    }
    for coll, filt in clear_filters.items():
        deleted = await db[coll].delete_many(filt)
        if deleted.deleted_count:
            print(f"  Cleared {deleted.deleted_count} old seed records from {coll}")

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

    # --- 2. data_container + internal_transaction (matching amounts/statuses) ---
    all_data_containers = []
    all_internal_txns = []

    for partner in PARTNERS[:2]:
        source_file_id = file_records[0].id if partner == "MOMO" else file_records[1].id
        total = count

        # 2a: generate data_container records first
        dc_records = []
        for i in range(total):
            status = _random_status()
            amount = _random_amount()
            trace = _random_trace(partner, i)
            trans_date = _random_trans_date()
            dc_extra = {
                "service": random.choice(SERVICES),
                "portal": random.choice(PORTALS),
                "provider": partner,
            }
            dc = DataContainer(
                _id=_uuid.uuid4(),
                requestId=_uuid.uuid4(),
                identify=partner,
                workflowType="UPC",
                reconciliationDate=RECON_DATE,
                operationStatus="COMPLETED",
                reconciliationStatus="",
                sourceFileId=source_file_id,
                partnerData=PartnerData(
                    _id=str(100000000 + i),
                    trace=trace,
                    status=status,
                    amount=amount,
                    currency="VND",
                    transDate=trans_date,
                    extra=dc_extra,
                ),
                createdBy=SEED_TAG,
            )
            dc_records.append(dc)
        all_data_containers.extend(dc_records)

        # 2b: generate internal_transaction — use the SAME amount/status
        # for the first `internal_count` records so reconciliation matches them
        internal_count = int(total * 0.85)

        # Of the matching ones, some will be MATCHED (same amount+status)
        # and some will be AMOUNT_MISMATCH/STATUS_MISMATCH (intentionally altered)
        matched_count_local = int(internal_count * 0.85)
        amt_mismatch_local = int(internal_count * 0.10)
        status_mismatch_local = internal_count - matched_count_local - amt_mismatch_local

        internal_txns = []
        for i in range(internal_count):
            txn_time = RECON_DATE + timedelta(
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59),
            )

            src = dc_records[i]
            src_amount = src.partner_data.amount
            src_status = src.partner_data.status

            if i < matched_count_local:
                # MATCHED: same amount, same status
                it_amount = src_amount
                it_status = src_status
            elif i < matched_count_local + amt_mismatch_local:
                # AMOUNT_MISMATCH: different amount
                offset = Decimal(str(random.randint(1000, 50000)))
                it_amount = src_amount + offset if random.random() < 0.5 else src_amount - offset
                if it_amount < Decimal("0"):
                    it_amount = offset
                it_status = src_status
            else:
                # STATUS_MISMATCH: same amount, different status
                it_amount = src_amount
                other_statuses = [s for s in ["SUCCESS", "FAILED", "PENDING", "REVERSED"] if s != src_status]
                it_status = random.choice(other_statuses)

            it = InternalTransaction(
                _id=f"int_{partner}_{i}",
                partner=partner,
                partnerTxnId=src.partner_data.trace,
                amount=it_amount,
                currency="VND",
                status=it_status,
                transactionTime=txn_time,
                createdAt=datetime.now(timezone.utc),
                updatedAt=datetime.now(timezone.utc),
            )
            internal_txns.append(it)
        all_internal_txns.extend(internal_txns)

        # 2c: generate MISSING_PARTNER internal_transactions (extra IT records with no matching DC)
        missing_ptnr_count = int(total * 0.07)
        for i in range(missing_ptnr_count):
            txn_time = RECON_DATE + timedelta(
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59),
            )
            it = InternalTransaction(
                _id=f"int_missing_{partner}_{i}",
                partner=partner,
                partnerTxnId=f"int_only_{partner}_{i}",
                amount=_random_amount(),
                currency="VND",
                status=random.choice(["SUCCESS", "SUCCESS", "SUCCESS", "FAILED"]),
                transactionTime=txn_time,
                createdAt=datetime.now(timezone.utc),
                updatedAt=datetime.now(timezone.utc),
            )
            all_internal_txns.append(it)

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

    # --- summary (no pre-generated reconciliation — engine will produce it) ---
    total_dc = len(all_data_containers)
    total_it = len(all_internal_txns)
    # Only 2 partners (MOMO, VNPAY) — omit ZALOPAY for brevity
    tracked_count = count * 2

    # These are the EXPECTED reconciliation results after running the engine
    # For each partner:
    internal_per_partner = int(count * 0.85)
    missing_ptnr_per_partner = int(count * 0.07)
    matched_per_partner = int(internal_per_partner * 0.85)
    amt_mismatch_partner = int(internal_per_partner * 0.10)
    status_mismatch_partner = internal_per_partner - matched_per_partner - amt_mismatch_partner
    missing_int_per_partner = count - internal_per_partner
    total_matched = matched_per_partner * 2
    total_amt = amt_mismatch_partner * 2
    total_status = status_mismatch_partner * 2
    total_missing_int = missing_int_per_partner * 2
    total_missing_ptnr = missing_ptnr_per_partner * 2

    print(f"\n--- Seed Summary ---")
    print(f"  MATCHED:          {total_matched}")
    print(f"  AMOUNT_MISMATCH:  {total_amt}")
    print(f"  STATUS_MISMATCH:  {total_status}")
    print(f"  MISSING_INTERNAL: {total_missing_int}")
    print(f"  MISSING_PARTNER:  {total_missing_ptnr}")

    print(f"\n  MATCHED rate:      {(total_matched/tracked_count)*100:.1f}%")
    print(f"  AMOUNT_MISMATCH:  {(total_amt/tracked_count)*100:.1f}%")
    print(f"  STATUS_MISMATCH:  {(total_status/tracked_count)*100:.1f}%")
    print(f"  MISSING_INTERNAL: {(total_missing_int/tracked_count)*100:.1f}%")
    print(f"  MISSING_PARTNER:  {(total_missing_ptnr/tracked_count)*100:.1f}%")
    print(f"\n  Total data_container:  {total_dc}")
    print(f"  Total internal_txn:  {total_it}")
    print(f"\n✅ Done. Run `uv run python run.py --reconcile 2024-07-07 --partner MOMO` to test reconciliation.")

    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed pipeline test data")
    parser.add_argument("--count", type=int, default=500, help="Number of records per partner (default: 500)")
    parser.add_argument("--clear", action="store_true", help="Clear all seed-generated data")
    args = parser.parse_args()
    asyncio.run(seed(args))
