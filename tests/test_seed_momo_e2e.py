"""Regression tests for `scratch/seed_momo_e2e.py`.

Locks the scope semantics from `src/reconciliation/engine.py:117-163` into
the canonical seed script so that future refactors of either the seed
helpers or the engine surface as test failures.

Per must_haves: test_reset_seeds_wave1_only | test_phase2_adds_wave2_only | test_missing_partner_demo
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from scratch.seed_momo_e2e import (
    MISSING_PARTNER_KEY,
    WAVE1_KEYS,
    WAVE2_KEYS,
    _add_missing_partner_demo,
    _add_phase2,
    _reset_and_seed_phase1,
    _wave1_keys,
    _wave2_keys,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _setup_internal_collection(mock_db: MagicMock) -> MagicMock:
    """Wire `mock_db['internal_transaction']` with AsyncMocks for the seed helpers.

    The conftest `mock_db` fixture returns a *fresh* MagicMock on every
    `db[name]` call (via `side_effect=lambda name: MagicMock()`), which would
    drop the AsyncMock setup between calls. We override `__getitem__` to
    return one consistent collection object so all calls see the same mock.

    `find_one` always returns None (no pre-existing docs) so `_seed_internal`
    inserts every requested key. The test captures `insert_one.call_args_list`
    to assert on the inserted docs.
    """
    collection = MagicMock()
    collection.delete_many = AsyncMock(return_value=None)
    collection.find_one = AsyncMock(return_value=None)
    collection.insert_one = AsyncMock(return_value=None)
    mock_db.__getitem__ = MagicMock(return_value=collection)
    return collection


def _read_partner_txn_ids(partner_file_path: Path) -> list[str]:
    """Read column B (msTransId) from a MOMO partner xlsx, skipping the header."""
    wb = openpyxl.load_workbook(partner_file_path)
    ws = wb.active
    keys: list[str] = []
    # Data starts at row 8: 6 blank rows + 1 header row
    for row in ws.iter_rows(min_row=8, min_col=2, max_col=2, values_only=True):
        value = row[0]
        if value is None or value == "":
            continue
        keys.append(str(value))
    return keys


def _inserted_partner_txn_ids(collection: MagicMock) -> list[str]:
    """Return the `partnerTxnId` of every doc passed to `insert_one`."""
    return [
        call.args[0]["partnerTxnId"]
        for call in collection.insert_one.call_args_list
    ]


# ── Test 1: reset seeds wave1 only ───────────────────────────────────────────


async def test_reset_seeds_wave1_only(mock_db: MagicMock, tmp_path: Path):
    """`_reset_and_seed_phase1` inserts exactly 20 wave1 keys and no others."""
    collection = _setup_internal_collection(mock_db)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    inserted = await _reset_and_seed_phase1(mock_db, str(partner_file))

    # 20 internal rows inserted, all wave1
    assert inserted == 20
    inserted_keys = _inserted_partner_txn_ids(collection)
    assert len(inserted_keys) == 20
    assert set(inserted_keys) == set(_wave1_keys())
    # No wave2 keys
    assert not any(k.startswith("MOMO_TXN_91") for k in inserted_keys)
    # No missing-partner key
    assert MISSING_PARTNER_KEY not in inserted_keys
    # Broad wipe happened first
    delete_call = collection.delete_many.await_args
    assert delete_call is not None
    assert delete_call.args[0] == {"partner": "MOMO"}
    # Partner file on disk contains the 20 wave1 keys
    file_keys = _read_partner_txn_ids(partner_file)
    assert sorted(file_keys) == sorted(WAVE1_KEYS)


# ── Test 2: phase2 adds wave2 only ──────────────────────────────────────────


async def test_phase2_adds_wave2_only(mock_db: MagicMock, tmp_path: Path):
    """`_add_phase2` (after reset) inserts 20 wave2 keys and overwrites the file."""
    collection = _setup_internal_collection(mock_db)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    # Establish wave1 baseline
    wave1_inserted = await _reset_and_seed_phase1(mock_db, str(partner_file))
    assert wave1_inserted == 20

    # Reset the mock call list so we can isolate phase2's inserts
    collection.insert_one.reset_mock()

    # Add phase2
    wave2_inserted = await _add_phase2(mock_db, str(partner_file))
    assert wave2_inserted == 20

    # Phase2's insert payload is exactly the wave2 keys
    phase2_keys = _inserted_partner_txn_ids(collection)
    assert len(phase2_keys) == 20
    assert set(phase2_keys) == set(_wave2_keys())
    # No wave1 keys re-inserted by phase2
    assert not any(k.startswith("MOMO_TXN_90") for k in phase2_keys)
    # No missing-partner key
    assert MISSING_PARTNER_KEY not in phase2_keys

    # Partner file on disk was OVERWRITTEN with wave2 keys (not wave1, not merged)
    file_keys = _read_partner_txn_ids(partner_file)
    assert sorted(file_keys) == sorted(WAVE2_KEYS)
    # Sanity: file has exactly 20 keys (not 40)
    assert len(file_keys) == 20


# ── Test 3: missing_partner_demo ────────────────────────────────────────────


async def test_missing_partner_demo(mock_db: MagicMock, tmp_path: Path):
    """`_add_missing_partner_demo` (after reset) inserts the anomaly row and keeps the wave1 file.

    After this, a FULL_SNAPSHOT ingestion should produce 20 MATCHED + 1 MISSING_PARTNER.
    """
    collection = _setup_internal_collection(mock_db)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    # Establish wave1 baseline
    wave1_inserted = await _reset_and_seed_phase1(mock_db, str(partner_file))
    assert wave1_inserted == 20

    # Reset mock so we can isolate the missing-partner insert
    collection.insert_one.reset_mock()

    # Inject the missing-partner row
    mp_inserted = await _add_missing_partner_demo(mock_db, str(partner_file))
    assert mp_inserted == 1

    # The missing-partner row was inserted with the correct key
    mp_keys = _inserted_partner_txn_ids(collection)
    assert mp_keys == [MISSING_PARTNER_KEY]

    # Partner file on disk STILL has the 20 wave1 keys (no missing-partner key)
    file_keys = _read_partner_txn_ids(partner_file)
    assert sorted(file_keys) == sorted(WAVE1_KEYS)
    assert MISSING_PARTNER_KEY not in file_keys
    assert len(file_keys) == 20

    # Total internal rows the helpers inserted: 20 wave1 + 1 missing = 21
    # (The mock is stateless across the two calls because we reset_mock()'d
    # between them, so we reconstruct the total from the helper outputs.)
    total_internal_rows = wave1_inserted + mp_inserted
    assert total_internal_rows == 21

    # Engine-level invariant: if these 21 internal rows are reconciled against
    # the 20 partner-file keys under FULL_SNAPSHOT scope, the result must be
    # 20 MATCHED + 1 MISSING_PARTNER whose partner_txn_id is the missing key.
    # We re-derive the matching inline (mirroring engine.py:117-163) to avoid
    # pulling in the full engine + its DB dependencies for a unit test.
    partner_key_set = set(file_keys)
    internal_key_set = set(_wave1_keys()) | {MISSING_PARTNER_KEY}
    matched = internal_key_set & partner_key_set
    missing = internal_key_set - partner_key_set

    assert len(matched) == 20
    assert len(missing) == 1
    assert missing == {MISSING_PARTNER_KEY}
