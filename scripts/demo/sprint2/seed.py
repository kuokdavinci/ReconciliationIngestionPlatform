"""Seed a real DB-backed ViettelPay Sprint 2 recovery demo.

``reset`` wipes only VIETTELPAY demo data, inserts six matching internal
transactions, creates the API fetch configuration without an approved mapping,
and arms the page-2 failure state. The checkpoint is created by the first
manual Run Now, not pre-seeded. The source endpoint is served by
``mock_api.py``.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, time
from decimal import Decimal
import os
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import delete

from scripts.demo.sprint2.fixture import reset_viettelpay_fixture
from scripts.demo.sprint2.mock_api import DEFAULT_STATE_FILE, write_state
from src.config.settings import settings
from src.core.enums import FileType, TransactionStatus
from src.domain.fetch_config.models import (
    APIConfig,
    APIPaginationConfig,
    FetchConfig,
    FetchMethod,
)
from src.domain.internal_transaction.models import InternalTransaction
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
)
from src.infrastructure.persistence.postgres_connection import get_pg_engine
from src.infrastructure.persistence.postgres_schema import (
    InternalTransactionTable,
    PartnerTransactionTable,
    ReconciliationResultTable,
)


PARTNER = "VIETTELPAY"
FETCH_CONFIG_ID = UUID("22222222-2222-2222-2222-222222222222")
MAPPING_CONFIG_ID = "33333333-3333-3333-3333-333333333333"
API_ENDPOINT = os.getenv(
    "VIETTELPAY_SPRINT2_API_ENDPOINT",
    "http://viettelpay-mock:8001/viettelpay/settlement",
)
FIXTURE_DIR = Path("mock_data/viettelpay_sprint2")
TRANSACTION_IDS = [f"VTP-{index:03d}" for index in range(1, 7)]


def _today_utc() -> datetime:
    """Return the current business-day start represented as UTC."""

    business_timezone = ZoneInfo(settings.business_timezone)
    local_day = datetime.now(business_timezone).date()
    return datetime.combine(local_day, time.min, tzinfo=business_timezone).astimezone(UTC)


def _build_internal_transactions(day: datetime) -> list[InternalTransaction]:
    now = datetime.now(UTC).replace(tzinfo=None)
    return [
        InternalTransaction(
            _id=f"INT_{PARTNER}_{txn_id}",
            partner=PARTNER,
            partnerTxnId=txn_id,
            amount=Decimal(index * 100000),
            currency="VND",
            status=TransactionStatus.SUCCESS,
            transactionTime=day.replace(tzinfo=None),
            createdAt=now,
            updatedAt=now,
        )
        for index, txn_id in enumerate(TRANSACTION_IDS, start=1)
    ]


def _mapping_document(now: datetime) -> dict:
    return {
        "_id": MAPPING_CONFIG_ID,
        "partner": PARTNER,
        "workflowType": "UPC",
        "fileType": FileType.SETTLEMENT.value,
        "sheetName": "JSON",
        "startRow": 1,
        "fieldMappings": [
            {"path": "id", "sourceField": "id", "type": "STRING", "required": True},
            {"path": "trace", "sourceField": "trace", "type": "STRING", "required": True},
            {"path": "amount", "sourceField": "amount", "type": "DECIMAL", "required": True},
            {"path": "currency", "sourceField": "currency", "type": "STRING", "required": True},
            {
                "path": "status",
                "sourceField": "status",
                "type": "MAPPING",
                "mapping": {"SUCCESS": "SUCCESS", "FAILED": "FAILED"},
            },
            {"path": "transDate", "sourceField": "transDate", "type": "DATE", "required": True},
            {"path": "extra.provider", "constant": PARTNER, "type": "CONSTANT"},
        ],
        "configVersion": "sprint2-v1",
        "status": "PENDING_APPROVAL",
        "createdAt": now,
    }


def _fetch_config(now: datetime) -> FetchConfig:
    return FetchConfig(
        _id=FETCH_CONFIG_ID,
        partner=PARTNER,
        fetchMethod=FetchMethod.API,
        enabled=True,
        schedule="0 0 * * *",
        validateRows=True,
        localDownloadDir="./downloads/viettelpay_sprint2",
        cleanupAfterIngest=False,
        api=APIConfig(
            baseUrl=API_ENDPOINT,
            method="GET",
            timeout=10,
            downloadDir="./downloads/viettelpay_sprint2",
            pagination=APIPaginationConfig(
                pageParam="page",
                cursorParam="cursor",
                itemsPath="items",
                nextCursorPath="nextCursor",
                maxPages=3,
            ),
        ),
        createdAt=now,
        updatedAt=now,
    )


async def _wipe_mongo(db) -> None:
    for collection, field in (
        ("reconciliation_result", "partner"),
        ("reconciliation_file", "partner"),
        ("data_container", "identify"),
        ("review_packet", "partner"),
        ("reconciliation_mapping_config", "partner"),
        ("reconciliation_mapping_config_history", "partner"),
        ("fetch_config", "partner"),
        ("ingestion_checkpoint", "partner"),
        ("ingestion_quarantine_record", "partner"),
        ("partner_runtime_run", "partner"),
        ("post_approval_run", "partner"),
        ("reconciliation_review_record", "partner"),
        ("copilot_action", "partner"),
    ):
        await db[collection].delete_many({field: PARTNER})
    await db["audit_event"].delete_many({"metadata.partner": PARTNER})


async def _wipe_postgres() -> None:
    engine = get_pg_engine()
    async with engine.begin() as connection:
        await connection.execute(
            delete(ReconciliationResultTable).where(
                ReconciliationResultTable.partner == PARTNER
            )
        )
        await connection.execute(
            delete(PartnerTransactionTable).where(
                PartnerTransactionTable.identify == PARTNER
            )
        )
        await connection.execute(
            delete(InternalTransactionTable).where(
                InternalTransactionTable.partner == PARTNER
            )
        )


def _reset_local_demo_files(output_dir: Path) -> None:
    """Remove only generated Sprint 2 fixture/download artifacts."""

    for path in output_dir.glob("page-*.json"):
        path.unlink(missing_ok=True)
    (output_dir / "manifest.json").unlink(missing_ok=True)
    (output_dir / DEFAULT_STATE_FILE.name).unlink(missing_ok=True)

    # A custom output directory is used by isolated tests; never let it
    # trigger cleanup in the repository-wide download directory.
    if output_dir.resolve() != FIXTURE_DIR.resolve():
        return

    download_dir = Path("downloads/viettelpay_sprint2")
    for path in download_dir.glob("api_data_*"):
        path.unlink(missing_ok=True)


async def reset_demo(output_dir: Path = FIXTURE_DIR) -> dict[str, int | str]:
    """Reset all VIETTELPAY demo data and arm the page 2 failure state."""

    day = _today_utc()
    now = datetime.now(UTC)
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    try:
        _reset_local_demo_files(output_dir)
        await _wipe_mongo(db)
        await _wipe_postgres()

        config = _fetch_config(now)
        await FetchConfigRepository(db).create(config)
        await InternalTransactionRepository().insert_many(_build_internal_transactions(day))
        write_state(DEFAULT_STATE_FILE, failures=3)
        manifest = reset_viettelpay_fixture(output_dir, endpoint=API_ENDPOINT)
    finally:
        client.close()

    print(f"Reset complete for {PARTNER} on {day:%Y-%m-%d}")
    print("Seeded API fetch config and 6 internal rows; no approved mapping")
    print("Mock API failure mode armed: the next Run Now will fail at page 2")
    print(f"Fixture manifest: {manifest}")
    return {"partner": PARTNER, "fetchMethod": FetchMethod.API.value, "internalRows": 6}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["reset"])
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args()
    asyncio.run(reset_demo(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
