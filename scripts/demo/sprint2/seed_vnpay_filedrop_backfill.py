"""Reset a deterministic VNPAY FileDrop fixture for ordered backfill demos."""

import argparse
import asyncio
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorClient
from openpyxl import Workbook

from src.config.settings import settings
from src.core.enums import TransactionStatus
from src.domain.fetch_config.models import FetchConfig, FetchMethod, FileDropConfig
from src.domain.internal_transaction.models import InternalTransaction
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository

DEFAULT_PARTNER = "VNPAY"
DEFAULT_FILE_DIR = Path("./mock_data")
DEFAULT_FROM_DAYS_AGO = 3
SEED_PREFIX = "seed-vnpay-filedrop-backfill"


def build_backfill_dates(from_date: str, to_date: str) -> list[date]:
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    if start > end:
        raise ValueError("from date must be on or before to date")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def build_source_filename(day: date) -> str:
    return f"settlement_{DEFAULT_PARTNER}_{day:%Y%m%d}.xlsx"


def build_fetch_config() -> FetchConfig:
    return FetchConfig(
        partner=DEFAULT_PARTNER,
        fetchMethod=FetchMethod.FILEDROP,
        enabled=True,
        schedule="none",
        localDownloadDir=str(DEFAULT_FILE_DIR),
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(
            directory=str(DEFAULT_FILE_DIR),
            pattern="settlement_VNPAY_{date:%Y%m%d}.xlsx",
        ),
    )


def write_source_file(directory: Path, day: date) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / build_source_filename(day)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["id", "trace", "amount", "status", "transDate"])
    for index in range(1, 4):
        sheet.append([
            f"VNPAY_{day:%Y%m%d}_{index:03d}",
            f"TRACE_{day:%Y%m%d}_{index:03d}",
            100000 + index * 5000,
            "SUCCESS",
            day.isoformat(),
        ])
    workbook.save(path)
    return path


def build_internal_transactions(day: date) -> list[InternalTransaction]:
    """Build the source-of-truth rows that correspond to one fixture file."""

    business_noon = datetime.combine(
        day,
        time(hour=12),
        tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"),
    )
    now = datetime.now(timezone.utc)
    return [
        InternalTransaction(
            _id=f"INT_{DEFAULT_PARTNER}_{day:%Y%m%d}_{index:03d}",
            partner=DEFAULT_PARTNER,
            # The reconciliation key resolver prefers the trace column when
            # both id and trace are present in a partner row.
            partnerTxnId=f"TRACE_{day:%Y%m%d}_{index:03d}",
            amount=Decimal(100000 + index * 5000),
            currency="VND",
            status=TransactionStatus.SUCCESS,
            transactionTime=business_noon,
            createdAt=now,
            updatedAt=now,
        )
        for index in range(1, 4)
    ]


def build_internal_preview(day: date) -> list[dict[str, str]]:
    """Return the bounded packet preview before the scope endpoint is called."""

    return [
        {
            "id": f"INT_{DEFAULT_PARTNER}_{day:%Y%m%d}_{index:03d}",
            "partnerTxnId": f"TRACE_{day:%Y%m%d}_{index:03d}",
            "amount": str(Decimal(100000 + index * 5000)),
            "currency": "VND",
            "status": "SUCCESS",
            "transactionTime": datetime.combine(
                day,
                time(hour=12),
                tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"),
            ).isoformat(),
        }
        for index in range(1, 4)
    ]


async def clear_postgres_fixture() -> None:
    """Remove all VNPAY source/result rows before rebuilding the fixture."""

    from sqlalchemy import delete

    from src.infrastructure.persistence.postgres_connection import get_pg_engine
    from src.infrastructure.persistence.postgres_schema import (
        InternalTransactionTable,
        PartnerTransactionTable,
        ReconciliationResultTable,
    )

    engine = get_pg_engine()
    async with engine.begin() as connection:
        await connection.execute(
            delete(ReconciliationResultTable).where(
                ReconciliationResultTable.partner == DEFAULT_PARTNER
            )
        )
        await connection.execute(
            delete(PartnerTransactionTable).where(
                PartnerTransactionTable.identify == DEFAULT_PARTNER
            )
        )
        await connection.execute(
            delete(InternalTransactionTable).where(
                InternalTransactionTable.partner == DEFAULT_PARTNER
            )
        )


def build_draft_mapping(day: date) -> dict:
    mapping_id = f"{SEED_PREFIX}-mapping"
    return {
        "_id": mapping_id,
        "partner": DEFAULT_PARTNER,
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "trace", "column": 2, "type": "STRING"},
            {"path": "amount", "column": 3, "type": "DECIMAL"},
            {"path": "currency", "type": "CONSTANT", "constant": "VND", "required": True},
            {"path": "status", "column": 4, "type": "STRING"},
            {"path": "transDate", "column": 5, "type": "DATE"},
        ],
        "configVersion": "VNPAY_BACKFILL_DRAFT_V1",
        "configHealth": {"status": "PENDING_APPROVAL", "seedTag": SEED_PREFIX},
        "structureSignature": {
            "headers": ["id", "trace", "amount", "status", "transDate"],
            "headerRowIndex": 1,
            "firstDataRowIndex": 2,
        },
        "status": "PENDING_APPROVAL",
        "createdAt": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
    }


def build_review_packet(day: date, file_path: Path) -> dict:
    packet_id = f"{SEED_PREFIX}-packet-{day:%Y%m%d}"
    created_at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    return {
        "_id": packet_id,
        "sourceType": "SCHEDULER_JOB",
        "partner": DEFAULT_PARTNER,
        "fileName": file_path.name,
        "fileTypeDetected": "SETTLEMENT",
        "draftMappingId": f"{SEED_PREFIX}-mapping",
        "draftMappingVersion": "VNPAY_BACKFILL_DRAFT_V1",
        "sourceFilePath": str(file_path),
        "reconciliationDate": created_at,
        "scopeType": "FULL_SNAPSHOT",
        "scopeConfidence": 0.99,
        "scopeReason": ["Deterministic VNPAY FileDrop backfill fixture."],
        "scopeSignals": {"seedTag": SEED_PREFIX, "backfillFixture": True},
        "recommendedAction": {"type": "APPROVE"},
        "parseStrategy": {"sheetName": "Sheet1", "startRow": 2},
        "validationGates": [],
        "samplePreview": [
            {"id": f"VNPAY_{day:%Y%m%d}_001", "trace": f"TRACE_{day:%Y%m%d}_001", "amount": 105000, "status": "SUCCESS", "transDate": day.isoformat()},
        ],
        "internalRecordCount": 3,
        "internalPreview": build_internal_preview(day),
        "riskSummary": {"level": "LOW"},
        "runtimeDecisionHint": "APPROVE_ACTIVATE_NEXT_RUNTIME",
        "status": "PENDING",
        "createdAt": created_at,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reset",), nargs="?", default="reset")
    parser.add_argument("--from-date", default=os.getenv("VNPAY_BACKFILL_FROM"))
    parser.add_argument("--to-date", default=os.getenv("VNPAY_BACKFILL_TO"))
    parser.add_argument("--file-dir", default=str(DEFAULT_FILE_DIR))
    return parser.parse_args()


def _default_dates() -> tuple[str, str]:
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    return (
        (today - timedelta(days=DEFAULT_FROM_DAYS_AGO)).isoformat(),
        today.isoformat(),
    )


async def reset_fixture(from_date: str, to_date: str, file_dir: str) -> list[Path]:
    days = build_backfill_dates(from_date, to_date)
    directory = Path(file_dir)
    for existing in directory.glob("settlement_VNPAY_*.xlsx"):
        existing.unlink()

    files = [write_source_file(directory, day) for day in days]
    # The backfill service intentionally skips weekends. Attach the initial
    # approval packet to the first day that the ordered runner can process;
    # otherwise a Sunday fixture file would be approved for a Monday run.
    first_day = next(day for day in days if day.weekday() < 5)
    first_file = files[days.index(first_day)]
    await clear_postgres_fixture()
    internal_repository = InternalTransactionRepository()
    await internal_repository.insert_many(
        [row for business_date in days for row in build_internal_transactions(business_date)]
    )
    client = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[settings.db_name]
        await client.admin.command("ping")
        await db["fetch_config"].delete_many({"partner": DEFAULT_PARTNER})
        await db["reconciliation_mapping_config"].delete_many({"partner": DEFAULT_PARTNER})
        await db["review_packet"].delete_many({"partner": DEFAULT_PARTNER})
        await db["backfill_run"].delete_many({"partner": DEFAULT_PARTNER})
        await db["partner_runtime_run"].delete_many({"partner": DEFAULT_PARTNER})
        await db["ingestion_checkpoint"].delete_many({"partner": DEFAULT_PARTNER})
        await db["reconciliation_file"].delete_many({"partner": DEFAULT_PARTNER})
        await FetchConfigRepository(db).create(build_fetch_config())
        await db["reconciliation_mapping_config"].insert_one(build_draft_mapping(first_day))
        await db["review_packet"].insert_one(build_review_packet(first_day, first_file))
    finally:
        client.close()
    return files


async def main() -> None:
    args = _parse_args()
    default_from, default_to = _default_dates()
    from_date = args.from_date or default_from
    to_date = args.to_date or default_to
    files = await reset_fixture(from_date, to_date, args.file_dir)
    print(f"Reset {DEFAULT_PARTNER} FileDrop backfill fixture: {from_date} -> {to_date}")
    for path in files:
        print(f"  {path}")
    print("Open Schedule UI, select VNPAY, and start Backfill after approving the mapping.")


if __name__ == "__main__":
    asyncio.run(main())
