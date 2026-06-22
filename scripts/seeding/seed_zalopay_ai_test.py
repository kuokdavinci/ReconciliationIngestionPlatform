"""Seed a ZaloPay AI-detect test case.

Creates:
- a FileDrop fetch config for ZALOPAY
- a weird-format ZaloPay data file that should trigger stale/AI detection

Usage:
    uv run python scripts/seed_zalopay_ai_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from src.config.settings import settings
from src.models.fetch_config import FetchConfigRepository
from src.models.mapping_config import MappingConfigRepository


WEIRD_DIR = Path("./sftp_data/zalopay_weird")
WEIRD_DIR.mkdir(parents=True, exist_ok=True)


def _write_weird_file(path: Path) -> None:
    # Deliberately unusual structure: no obvious headers, mixed order, extra columns.
    rows = [
        ["ZP-20240708-001", "2024/07/08 08:01:02", "SUCCESS", "250000", "trace_001", "EXTRA_A"],
        ["ZP-20240708-002", "2024/07/08 08:03:11", "FAILED", "150000", "trace_002", "EXTRA_B"],
        ["ZP-20240708-003", "2024/07/08 08:05:19", "SUCCESS", "99000", "trace_003", "EXTRA_C"],
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _write_weird_file_2(path: Path) -> None:
    rows = [
        ["ZP-20240708-101", "2024/07/08 09:11:02", "SUCCESS", "188000", "trace_101", "EXTRA_D"],
        ["ZP-20240708-102", "2024/07/08 09:12:19", "FAILED", "133000", "trace_102", "EXTRA_E"],
        ["ZP-20240708-103", "2024/07/08 09:14:45", "PENDING", "99000", "trace_103", "EXTRA_F"],
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


async def main() -> None:
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]

    # Fetch config: FileDrop so cronjob can pick the file locally.
    fetch_repo = FetchConfigRepository(db)
    await fetch_repo.delete_by_partner("ZALOPAY")
    await fetch_repo._collection.insert_one(
        {
            "_id": "11111111-1111-1111-1111-111111111111",
            "partner": "ZALOPAY",
            "fetchMethod": "FILEDROP",
            "enabled": True,
            "schedule": "0 0 * * *",
            "localDownloadDir": "./downloads",
            "cleanupAfterIngest": False,
            "archiveDir": None,
            "archiveRetentionDays": 30,
            "filedrop": {
                "directory": str(WEIRD_DIR),
                "pattern": "zalopay_20240708_weird_2.json",
            },
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }
    )

    # Ensure no old mapping config blocks the AI path.
    map_repo = MappingConfigRepository(db)
    await map_repo.collection.delete_many({"partner": "ZALOPAY"})

    weird_file = WEIRD_DIR / "zalopay_20240708_weird.json"
    _write_weird_file(weird_file)

    weird_file_2 = WEIRD_DIR / "zalopay_20240708_weird_2.json"
    _write_weird_file_2(weird_file_2)

    print(f"Seeded ZALOPAY fetch config and weird file: {weird_file}")
    print("Run the scheduler job once or call daily_partner_fetch_job() to trigger AI detect.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
