#!/usr/bin/env python3
"""Generate test data for reconciliation pipeline testing.

Produces partner data files in all supported formats (.xlsx, .csv, .json, .tsv)
and optionally seeds InternalTransaction records to MongoDB for end-to-end testing.

Usage:
    # Generate all formats
    python scripts/generate_test_data.py --output-dir test_data --count 1000

    # Generate single format
    python scripts/generate_test_data.py --format csv --output-dir test_data

    # Seed internal transactions to MongoDB (run after pipeline)
    python scripts/generate_test_data.py --seed-db --partner VNPAY --date 2024-07-08 --count 1000
"""

import argparse
import asyncio
import csv
import json
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import settings
from src.core.enums import TransactionStatus, ReconciliationStatus
from src.models.internal_transaction import InternalTransaction, InternalTransactionRepository
from src.models.reconciliation_result import ReconciliationResult, ReconciliationResultRepository

PARTNER = "VNPAY"
RECON_DATE = "2024-07-08"
RECON_DATE_DT = datetime(2024, 7, 8, tzinfo=timezone.utc)

BASE_AMOUNTS = [50000, 100000, 150000, 200000, 300000, 500000, 1000000, 2000000, 5000000]

HEADERS = ["id", "trace", "amount", "status", "transDate"]


def _generate_partner_records(count: int) -> list[dict]:
    records = []
    for i in range(count):
        idx = i + 1
        trace = f"VNPY240708TXN{idx:06d}"
        amount = random.choice(BASE_AMOUNTS) + random.randint(0, 999)
        status = random.choices(
            ["SUCCESS", "FAILED", "PENDING"],
            weights=[85, 10, 5],
            k=1,
        )[0]
        records.append({
            "id": f"VNP{idx:06d}",
            "trace": trace,
            "amount": amount,
            "status": status,
            "transDate": f"{RECON_DATE} {random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}",
        })
    return records


def _generate_internal_distribution(count: int) -> dict:
    matched = int(count * 0.90)
    amt_mismatch = 30
    status_mismatch = 20
    internal_only = 50
    return {
        "matched": matched,
        "amount_mismatch": amt_mismatch,
        "status_mismatch": status_mismatch,
        "partner_only": count - matched - amt_mismatch - status_mismatch,
        "internal_only": internal_only,
    }


def write_xlsx(filepath: str, records: list[dict]):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Header row (row 1) — skipped by start_row=2
    ws.append(HEADERS)

    for rec in records:
        ws.append([rec["id"], rec["trace"], rec["amount"], rec["status"], rec["transDate"]])

    wb.save(filepath)
    print(f"  Wrote: {filepath}  ({len(records)} rows + header)")


def write_csv(filepath: str, records: list[dict]):
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        for rec in records:
            writer.writerow([rec["id"], rec["trace"], rec["amount"], rec["status"], rec["transDate"]])
    print(f"  Wrote: {filepath}  ({len(records)} rows + header)")


def write_json(filepath: str, records: list[dict]):
    rows = [HEADERS]
    rows.extend([rec["id"], rec["trace"], rec["amount"], rec["status"], rec["transDate"]] for rec in records)
    with open(filepath, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"  Wrote: {filepath}  ({len(records)} data rows + header)")


def write_tsv(filepath: str, records: list[dict]):
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(HEADERS)
        for rec in records:
            writer.writerow([rec["id"], rec["trace"], rec["amount"], rec["status"], rec["transDate"]])
    print(f"  Wrote: {filepath}  ({len(records)} rows + header)")


async def seed_internal(db, partner: str, date_str: str, total: int):
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]

    internal_repo = InternalTransactionRepository(db)
    result_repo = ReconciliationResultRepository(db)

    partner_records = _generate_partner_records(total)
    dist = _generate_internal_distribution(total)

    # Parse date
    recon_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # Clear existing data
    await internal_repo.collection.delete_many({"partner": partner})
    await result_repo.collection.delete_many({"partner": partner, "date": date_str})
    print(f"  Cleared existing {partner} data")

    internal_docs: list[InternalTransaction] = []
    results: list[ReconciliationResult] = []

    idx = 0

    # 1. MATCHED
    for _ in range(dist["matched"]):
        rec = partner_records[idx]
        internal_docs.append(InternalTransaction(
            _id=f"INT_VNP_{idx:06d}",
            partner=partner,
            partnerTxnId=rec["trace"],
            amount=Decimal(str(rec["amount"])),
            currency="VND",
            status=TransactionStatus(rec["status"]),
            transactionTime=recon_date,
        ))
        results.append(ReconciliationResult(
            id=rec["trace"],
            partner=partner,
            date=date_str,
            partnerTxnId=rec["trace"],
            internalTxnId=f"INT_VNP_{idx:06d}",
            partnerAmount=Decimal(str(rec["amount"])),
            internalAmount=Decimal(str(rec["amount"])),
            partnerStatus=rec["status"],
            internalStatus=rec["status"],
            reconciliationStatus=ReconciliationStatus.MATCHED,
            partnerRecordId=rec["id"],
            internalRecordId=f"INT_VNP_{idx:06d}",
        ))
        idx += 1

    # 2. AMOUNT_MISMATCH
    for _ in range(dist["amount_mismatch"]):
        rec = partner_records[idx]
        diff = random.choice([5000, 10000, 15000])
        int_amount = Decimal(str(rec["amount"])) + Decimal(str(diff))
        internal_docs.append(InternalTransaction(
            _id=f"INT_VNP_{idx:06d}",
            partner=partner,
            partnerTxnId=rec["trace"],
            amount=int_amount,
            currency="VND",
            status=TransactionStatus(rec["status"]),
            transactionTime=recon_date,
        ))
        results.append(ReconciliationResult(
            id=rec["trace"],
            partner=partner,
            date=date_str,
            partnerTxnId=rec["trace"],
            internalTxnId=f"INT_VNP_{idx:06d}",
            partnerAmount=Decimal(str(rec["amount"])),
            internalAmount=int_amount,
            partnerStatus=rec["status"],
            internalStatus=rec["status"],
            reconciliationStatus=ReconciliationStatus.AMOUNT_MISMATCH,
            partnerRecordId=rec["id"],
            internalRecordId=f"INT_VNP_{idx:06d}",
        ))
        idx += 1

    # 3. STATUS_MISMATCH
    for _ in range(dist["status_mismatch"]):
        rec = partner_records[idx]
        int_status = "FAILED" if rec["status"] == "SUCCESS" else "SUCCESS"
        internal_docs.append(InternalTransaction(
            _id=f"INT_VNP_{idx:06d}",
            partner=partner,
            partnerTxnId=rec["trace"],
            amount=Decimal(str(rec["amount"])),
            currency="VND",
            status=TransactionStatus(int_status),
            transactionTime=recon_date,
        ))
        results.append(ReconciliationResult(
            id=rec["trace"],
            partner=partner,
            date=date_str,
            partnerTxnId=rec["trace"],
            internalTxnId=f"INT_VNP_{idx:06d}",
            partnerAmount=Decimal(str(rec["amount"])),
            internalAmount=Decimal(str(rec["amount"])),
            partnerStatus=rec["status"],
            internalStatus=int_status,
            reconciliationStatus=ReconciliationStatus.STATUS_MISMATCH,
            partnerRecordId=rec["id"],
            internalRecordId=f"INT_VNP_{idx:06d}",
        ))
        idx += 1

    # 4. Partner-only records (MISSING_INTERNAL) — already in partner_records[idx:]
    partner_only_start = idx
    idx += dist["partner_only"]
    for j in range(partner_only_start, idx):
        rec = partner_records[j]
        results.append(ReconciliationResult(
            id=rec["trace"],
            partner=partner,
            date=date_str,
            partnerTxnId=rec["trace"],
            partnerAmount=Decimal(str(rec["amount"])),
            partnerStatus=rec["status"],
            reconciliationStatus=ReconciliationStatus.MISSING_INTERNAL,
            partnerRecordId=rec["id"],
        ))

    # 5. Internal-only records (MISSING_PARTNER)
    for k in range(dist["internal_only"]):
        uid = idx + k
        trace = f"VNPY240708INTONLY{uid:06d}"
        amt = Decimal(str(random.choice(BASE_AMOUNTS) + random.randint(0, 999)))
        internal_docs.append(InternalTransaction(
            _id=f"INT_VNP_ONLY_{uid:06d}",
            partner=partner,
            partnerTxnId=trace,
            amount=amt,
            currency="VND",
            status=TransactionStatus.SUCCESS,
            transactionTime=recon_date,
        ))
        results.append(ReconciliationResult(
            id=trace,
            partner=partner,
            date=date_str,
            partnerTxnId=trace,
            internalTxnId=f"INT_VNP_ONLY_{uid:06d}",
            internalAmount=amt,
            internalStatus="SUCCESS",
            reconciliationStatus=ReconciliationStatus.MISSING_PARTNER,
            internalRecordId=f"INT_VNP_ONLY_{uid:06d}",
        ))

    # Insert to Mongo
    int_inserted = await internal_repo.insert_many(internal_docs)
    print(f"  Inserted {int_inserted} InternalTransaction records")

    # Clean + insert results
    target_ids = [r.id for r in results]
    await result_repo.collection.delete_many({"_id": {"$in": target_ids}})
    if results:
        serialized = [result_repo._to_mongo(r) for r in results]
        await result_repo.collection.insert_many(serialized)
    print(f"  Inserted {len(results)} ReconciliationResult records")

    # Summary
    by_status: dict[str, int] = {}
    for r in results:
        s = r.reconciliation_status.value
        by_status[s] = by_status.get(s, 0) + 1

    matched_count = by_status.get("MATCHED", 0)
    total_partner = dist["matched"] + dist["amount_mismatch"] + dist["status_mismatch"] + dist["partner_only"]
    mismatch_rate = round((total_partner - matched_count) / total_partner * 100, 2)

    print()
    print("--- Seed Summary ---")
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {status:25s} {count:4d}")
    print(f"\n  Total partner records:          {total_partner}")
    print(f"  Total internal records:         {int_inserted}")
    print(f"  Mismatch rate (partner-side):   {mismatch_rate}%")

    client.close()


def main():
    parser = argparse.ArgumentParser(description="Generate reconciliation test data")
    parser.add_argument("--output-dir", default="test_data", help="Output directory for data files")
    parser.add_argument("--format", choices=["xlsx", "csv", "json", "tsv", "all"], default="all",
                        help="Output file format (default: all)")
    parser.add_argument("--count", type=int, default=1000, help="Number of partner records (default: 1000)")
    parser.add_argument("--partner", default=PARTNER, help="Partner name")
    parser.add_argument("--date", default=RECON_DATE, help="Reconciliation date (YYYY-MM-DD)")
    parser.add_argument("--seed-db", action="store_true", help="Seed internal transactions + results to MongoDB")
    args = parser.parse_args()

    if args.seed_db:
        print(f"Seeding {args.partner} {args.date} with {args.count} records...")
        asyncio.run(seed_internal(
            db=None, partner=args.partner, date_str=args.date, total=args.count
        ))
        return

    records = _generate_partner_records(args.count)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.count} {args.partner} records for {args.date}")

    formats = ["xlsx", "csv", "json", "tsv"] if args.format == "all" else [args.format]
    writers = {
        "xlsx": write_xlsx,
        "csv": write_csv,
        "json": write_json,
        "tsv": write_tsv,
    }

    for fmt in formats:
        filepath = str(output_dir / f"{args.partner}_{args.date}.{fmt}")
        writers[fmt](filepath, records)

    print(f"\nDone. Generated {len(formats)} file(s) in {output_dir}/")
    print()
    print("Next steps:")
    for fmt in formats:
        filepath = output_dir / f"{args.partner}_{args.date}.{fmt}"
        print(f"  1. Upload config:  uv run python run.py --partner {args.partner}")
    print(f"  2. Run pipeline:    uv run python run.py --partner {args.partner} "
          f"--date {args.date} (with generated file in sftp_data/ or via --data)")
    print(f"  3. Reconcile:       uv run python run.py --reconcile {args.date} --partner {args.partner}")
    print(f"  4. Seed internal:   uv run python scripts/generate_test_data.py "
          f"--seed-db --partner {args.partner} --date {args.date} --count {args.count}")
    print("  5. Start API:       uv run python run.py --serve")
    print("  6. Start dash:      python frontend/server.py --port 5173 --api http://localhost:8000")


if __name__ == "__main__":
    main()
