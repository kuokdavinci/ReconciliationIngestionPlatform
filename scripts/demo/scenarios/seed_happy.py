"""Seed MOMO 2024-07-08 with happy-case reconciliation data.

Inserts reconciliation_result documents directly into MongoDB so the
dashboard and AI insights show a healthy state (mismatch rate < 2%).

Usage:
    uv run python scripts/demo/scenarios/seed_happy.py
"""

import asyncio
import random
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from src.config.settings import settings

RECON_DATE = "2024-07-08"
PARTNER = "MOMO"
TOTAL = 1000

# Happy-case distribution: 99.6% matched
MATCHED_COUNT = 996
AMOUNT_MISMATCH_COUNT = 2
STATUS_MISMATCH_COUNT = 1
MISSING_INTERNAL_COUNT = 1
MISSING_PARTNER_COUNT = 0


def _build_record(idx: int, status: str, amount: float) -> dict:
    txn_id = f"MOMO_STABLE_{idx:06d}"
    return {
        "_id": txn_id,
        "partner": PARTNER,
        "date": RECON_DATE,
        "partnerTxnId": txn_id,
        "internalTxnId": f"INT_MOMO_STABLE_{idx:06d}",
        "partnerAmount": amount,
        "internalAmount": amount,
        "partnerStatus": "SUCCESS" if status != "STATUS_MISMATCH" else "FAILED",
        "internalStatus": "SUCCESS",
        "reconciliationStatus": status,
        "partnerRecordId": f"PR_MOMO_STABLE_{idx:06d}",
        "internalRecordId": f"IR_MOMO_STABLE_{idx:06d}",
        "createdAt": datetime.now(timezone.utc),
    }


async def seed_happy():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    coll = db["reconciliation_result"]

    # Clear existing data for MOMO 2024-07-08
    deleted = await coll.delete_many({"partner": PARTNER, "date": RECON_DATE})
    if deleted.deleted_count:
        print(f"  Cleared {deleted.deleted_count} existing records for {PARTNER} {RECON_DATE}")

    records = []
    base_amounts = [50000, 100000, 150000, 200000, 300000, 500000, 1000000, 2000000, 5000000]

    for i in range(MATCHED_COUNT):
        amt = float(random.choice(base_amounts) + random.randint(0, 999))
        records.append(_build_record(i, "MATCHED", amt))

    i = MATCHED_COUNT
    for _ in range(AMOUNT_MISMATCH_COUNT):
        amt = float(random.choice(base_amounts) + random.randint(0, 999))
        rec = _build_record(i, "AMOUNT_MISMATCH", amt)
        rec["internalAmount"] = round(amt + random.choice([5000, 10000, 15000]), 2)
        records.append(rec)
        i += 1

    for _ in range(STATUS_MISMATCH_COUNT):
        amt = float(random.choice(base_amounts) + random.randint(0, 999))
        rec = _build_record(i, "STATUS_MISMATCH", amt)
        rec["internalStatus"] = "FAILED"
        records.append(rec)
        i += 1

    for _ in range(MISSING_INTERNAL_COUNT):
        amt = float(random.choice(base_amounts) + random.randint(0, 999))
        rec = _build_record(i, "MISSING_INTERNAL", amt)
        rec["internalTxnId"] = None
        rec["internalAmount"] = None
        rec["internalStatus"] = None
        rec["internalRecordId"] = None
        records.append(rec)
        i += 1

    await coll.insert_many(records)
    print(f"  Inserted {len(records)} reconciliation_result records")

    # Print summary
    by_status: dict[str, int] = {}
    for r in records:
        s = r["reconciliationStatus"]
        by_status[s] = by_status.get(s, 0) + 1

    matched = by_status.get("MATCHED", 0)
    mismatch_rate = round((TOTAL - matched) / TOTAL * 100, 2)

    print()
    print("--- Happy Case Summary ---")
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {status:25s} {count:4d}  ({count/TOTAL*100:.1f}%)")
    print(f"\n  Total:                {TOTAL}")
    print(f"  Mismatch rate:        {mismatch_rate}%")
    print(f"  Status:               {'HEALTHY' if mismatch_rate <= 2 else 'WARNING' if mismatch_rate <= 5 else 'CRITICAL'}")
    print()
    print("✅ Done. Start the API server and open the dashboard to see happy-case metrics.")
    print("   API:  uv run python run.py serve")
    print("   Dash: python frontend/server.py --port 5173 --api http://localhost:8000")

    client.close()


if __name__ == "__main__":
    asyncio.run(seed_happy())
