"""Canonical MOMO E2E seed script.

Replaces the legacy `seed_momo_scheduler_green.py` (which preloaded 40 internal
rows against a 19-row file and produced false `MISSING_PARTNER` results).

Modes (selected via CLI):
    reset                — wipe MOMO internal rows, seed 20 wave1 rows (9000-9019),
                           write a wave1 partner xlsx.
    phase2               — add 20 wave2 rows (9100-9119), OVERWRITE the partner
                           file with wave2 keys (so the engine sees
                           INCREMENTAL_APPEND scope and matches only wave2).
    missing_partner_demo — insert a single `MOMO_TXN_90_MISSING_PARTNER` internal
                           row and write a wave1 partner xlsx (so a
                           FULL_SNAPSHOT ingestion produces exactly 1 MISSING_PARTNER).

The helpers below (`_reset_and_seed_phase1`, `_add_phase2`,
`_add_missing_partner_demo`, `_seed_internal`, `_write_partner_file`,
`_wave1_keys`, `_wave2_keys`, `WAVE1_KEYS`, `WAVE2_KEYS`, `MISSING_PARTNER_KEY`)
are importable from tests for regression coverage.
"""

import argparse
import asyncio
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


PARTNER = "MOMO"

# Module-level constants for import convenience
WAVE1_KEYS: list[str] = [f"MOMO_TXN_90{i:02d}" for i in range(20)]
WAVE2_KEYS: list[str] = [f"MOMO_TXN_91{i:02d}" for i in range(20)]
MISSING_PARTNER_KEY: str = "MOMO_TXN_90_MISSING_PARTNER"
MISSING_PARTNER_AMOUNT: Decimal = Decimal("50000")


# ── Key helpers ──────────────────────────────────────────────────────────────


def _wave1_keys() -> list[str]:
    """Return a copy of the 20 wave1 keys (MOMO_TXN_9000..MOMO_TXN_9019)."""
    return list(WAVE1_KEYS)


def _wave2_keys() -> list[str]:
    """Return a copy of the 20 wave2 keys (MOMO_TXN_9100..MOMO_TXN_9119)."""
    return list(WAVE2_KEYS)


def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _date_str(day: datetime) -> str:
    return day.strftime("%Y-%m-%d")


def _amount_for_key(txn_id: str) -> Decimal:
    """Deterministic amount for a MOMO wave key (matches legacy script)."""
    if txn_id.startswith("MOMO_TXN_90"):
        suffix = txn_id.replace("MOMO_TXN_90", "")
        return Decimal(100000 + int(suffix) * 5000)
    if txn_id.startswith("MOMO_TXN_91"):
        suffix = txn_id.replace("MOMO_TXN_91", "")
        return Decimal(100000 + int(suffix) * 5000)
    if txn_id == MISSING_PARTNER_KEY:
        return MISSING_PARTNER_AMOUNT
    raise ValueError(f"Unsupported txn id: {txn_id}")


def _partner_file_path_for_day(day: datetime) -> Path:
    """Default production partner file path: ./sftp_data/settlement_MOMO_YYYYMMDD.xlsx.

    Also cleans up any stale settlement_MOMO_*.xlsx files in ./sftp_data so a
    second run on the same day does not leave debris.
    """
    sftp_dir = Path("./sftp_data")
    sftp_dir.mkdir(exist_ok=True)
    for old_file in sftp_dir.glob("settlement_MOMO_*.xlsx"):
        old_file.unlink()
    date_compact = _date_str(day).replace("-", "")
    return sftp_dir / f"settlement_MOMO_{date_compact}.xlsx"


# ── Partner file writer ──────────────────────────────────────────────────────


def _write_partner_file(
    path: str | Path,
    keys: list[str],
    *,
    day: Optional[datetime] = None,
) -> Path:
    """Overwrite the partner xlsx at `path` with one row per key.

    Layout matches the production MOMO ingestor: 6 blank rows, then a 30-column
    header row, then one data row per key. The reconciliation key (`msTransId`)
    lives in column 2 (B).
    """
    if day is None:
        day = _today_utc()
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    date_str = _date_str(day)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    for _ in range(6):
        ws.append([])

    headers = [""] * 30
    headers[0] = "STT"
    headers[1] = "msTransId"
    headers[4] = "msTotalAmount"
    headers[7] = "msNgayHoanThanh"
    headers[10] = "msMaHDon"
    headers[17] = "msTrangThaiGd"
    ws.append(headers)

    for index, txn_id in enumerate(keys, start=1):
        amount = _amount_for_key(txn_id)
        row = [""] * 30
        row[0] = str(index)
        row[1] = txn_id
        row[4] = str(amount)
        row[7] = f"{date_str} 12:00:00"
        row[10] = txn_id
        row[17] = "Thành công"
        ws.append(row)

    wb.save(out_path)
    return out_path


# ── Internal transaction helpers ─────────────────────────────────────────────


def _build_internal_doc(
    txn_id: str,
    day: datetime,
    *,
    amount: Optional[Decimal] = None,
) -> dict:
    """Build a Mongo doc for `internal_transaction` (camelCase aliases, Decimal128)."""
    if amount is None:
        amount = _amount_for_key(txn_id)
    now = datetime.now(timezone.utc)
    return {
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


async def _seed_internal(
    db,
    keys: list[str],
    *,
    day: Optional[datetime] = None,
) -> int:
    """Insert internal rows for the given keys (skips ones already present).

    Uses `db["internal_transaction"]` directly so the helper is testable with
    a mock db (see `tests/test_seed_momo_e2e.py`).
    """
    if day is None:
        day = _today_utc()
    collection = db["internal_transaction"]
    inserted = 0
    for txn_id in keys:
        existing = await collection.find_one(
            {"partner": PARTNER, "partnerTxnId": txn_id}
        )
        if existing:
            continue
        doc = _build_internal_doc(txn_id, day)
        await collection.insert_one(doc)
        inserted += 1
    return inserted


# ── High-level mode helpers (testable surface) ───────────────────────────────


async def _reset_and_seed_phase1(db, partner_file_path: str | Path) -> int:
    """Wipe MOMO internal rows, seed 20 wave1 rows, write wave1 partner xlsx.

    Returns the number of inserted internal rows (20 in the clean case).
    Does NOT touch the other MOMO collections (reconciliation_result, fetch_config,
    etc.) — the CLI `main()` does that full reset, but the helper itself stays
    narrowly focused on internal_transaction + the partner file so tests can
    mock just one collection.
    """
    day = _today_utc()
    collection = db["internal_transaction"]
    await collection.delete_many({"partner": PARTNER})
    inserted = await _seed_internal(db, _wave1_keys(), day=day)
    _write_partner_file(partner_file_path, _wave1_keys(), day=day)
    return inserted


async def _add_phase2(db, partner_file_path: str | Path) -> int:
    """Add 20 wave2 internal rows and OVERWRITE the partner file with wave2 keys.

    Does NOT delete the wave1 internal rows — they remain so the engine's
    INCREMENTAL_APPEND scope filter (engine.py:159-163) is the thing that
    scopes them out. This is what makes the wave2 run produce 20 MATCHED,
    0 MISSING_PARTNER.
    """
    day = _today_utc()
    inserted = await _seed_internal(db, _wave2_keys(), day=day)
    _write_partner_file(partner_file_path, _wave2_keys(), day=day)
    return inserted


async def _add_missing_partner_demo(db, partner_file_path: str | Path) -> int:
    """Add the intentional MOMO_TXN_90_MISSING_PARTNER internal row.

    Also writes a wave1 partner xlsx (20 wave1 keys, NO missing-partner key)
    so that a subsequent FULL_SNAPSHOT ingestion produces exactly:
        20 MATCHED + 1 MISSING_PARTNER
    Idempotent: deletes any pre-existing missing-partner row before inserting.
    """
    day = _today_utc()
    collection = db["internal_transaction"]
    await collection.delete_many(
        {"partner": PARTNER, "partnerTxnId": MISSING_PARTNER_KEY}
    )
    doc = _build_internal_doc(MISSING_PARTNER_KEY, day, amount=MISSING_PARTNER_AMOUNT)
    await collection.insert_one(doc)
    _write_partner_file(partner_file_path, _wave1_keys(), day=day)
    return 1


# ── CLI-only helpers (not part of the testable surface) ──────────────────────


async def _full_wipe(db) -> None:
    """Wipe all MOMO-related collections (production reset).

    `data_container` uses field name `identify`; the rest use `partner`.
    """
    await db["reconciliation_result"].delete_many({"partner": PARTNER})
    await db["reconciliation_file"].delete_many({"partner": PARTNER})
    await db["data_container"].delete_many({"identify": PARTNER})
    await db["review_packet"].delete_many({"partner": PARTNER})
    await db["reconciliation_mapping_config"].delete_many({"partner": PARTNER})
    await db["reconciliation_mapping_config_history"].delete_many({"partner": PARTNER})
    await db["fetch_config"].delete_many({"partner": PARTNER})


async def _ensure_fetch_config(db) -> None:
    """Create the MOMO fetch_config (FILEDROP → ./sftp_data) if missing."""
    repo = FetchConfigRepository(db)
    existing = await repo.find_by_partner(PARTNER)
    if existing is not None:
        return

    fetch_config = FetchConfig(
        partner=PARTNER,
        fetchMethod=FetchMethod.FILEDROP,
        enabled=True,
        schedule="0 0 * * *",
        localDownloadDir="./downloads",
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(directory="./sftp_data", pattern="settlement_MOMO_*.xlsx"),
    )
    await repo.create(fetch_config)


# ── CLI entry point ──────────────────────────────────────────────────────────


async def main(mode: str) -> None:
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    day = _today_utc()
    partner_file_path = _partner_file_path_for_day(day)

    try:
        if mode == "reset":
            await _full_wipe(db)
            inserted = await _reset_and_seed_phase1(db, partner_file_path)
            await _ensure_fetch_config(db)
            print(f"Reset complete for {PARTNER} on {_date_str(day)}")
            print(f"Seeded Phase 1 internal rows: {inserted}")
            print(f"Wrote partner file: {partner_file_path}")
        elif mode == "phase2":
            inserted = await _add_phase2(db, partner_file_path)
            await _ensure_fetch_config(db)
            print(f"Phase 2 data prepared for {PARTNER} on {_date_str(day)}")
            print(f"Added Phase 2 internal rows: {inserted}")
            print(f"Overwrote partner file: {partner_file_path}")
        elif mode == "missing_partner_demo":
            inserted = await _add_missing_partner_demo(db, partner_file_path)
            await _ensure_fetch_config(db)
            print(f"Missing-partner demo prepared for {PARTNER} on {_date_str(day)}")
            print(f"Inserted MISSING_PARTNER internal row: {inserted}")
            print(f"Wrote partner file (wave1 only, 20 keys): {partner_file_path}")
        else:
            raise ValueError(
                f"Unsupported mode: {mode!r}. "
                f"Expected one of: reset, phase2, missing_partner_demo"
            )
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed MOMO E2E data for phase-based testing."
    )
    parser.add_argument(
        "mode",
        choices=["reset", "phase2", "missing_partner_demo"],
        help="reset=clean Phase 1; phase2=add Wave 2; missing_partner_demo=inject MISSING_PARTNER row",
    )
    args = parser.parse_args()
    asyncio.run(main(args.mode))
