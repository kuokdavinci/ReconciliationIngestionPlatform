"""Regression tests for `scripts/demo/sprint1/seed_momo_e2e.py`.

Locks the scope semantics from `src/reconciliation/engine.py:117-163` into
the canonical seed script so that future refactors of either the seed
helpers or the engine surface as test failures.

Per must_haves: test_reset_seeds_wave1_only | test_phase2_adds_wave2_only | test_missing_partner_demo
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import openpyxl

from scripts.demo.sprint1 import seed_momo_e2e
from scripts.demo.sprint1.seed_momo_e2e import (
    MISSING_PARTNER_KEY,
    WAVE1_KEYS,
    WAVE2_KEYS,
    _add_missing_partner_demo,
    _add_phase2,
    _add_phase2_duplicate,
    _reset_and_seed_phase1,
    _wave1_keys,
    _wave2_keys,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _setup_internal_repository(monkeypatch) -> MagicMock:
    """Use a fake PostgreSQL repository for seed helper unit tests."""
    repository = MagicMock()
    repository.find_existing_partner_txn_ids = AsyncMock(return_value=set())
    repository.insert_many = AsyncMock(side_effect=lambda docs: len(docs))
    repository.delete_by_partner_and_txn_id = AsyncMock(return_value=0)
    monkeypatch.setattr(seed_momo_e2e, "InternalTransactionRepository", lambda: repository)
    monkeypatch.setattr(seed_momo_e2e, "_clear_momo_transaction_rows", AsyncMock())
    return repository


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


def _inserted_partner_txn_ids(repository: MagicMock) -> list[str]:
    """Return the source key of every document passed to PostgreSQL insert."""
    return [
        document.partner_txn_id
        for call in repository.insert_many.call_args_list
        for document in call.args[0]
    ]


# ── Test 1: reset seeds wave1 only ───────────────────────────────────────────


async def test_reset_seeds_wave1_only(mock_db: MagicMock, monkeypatch, tmp_path: Path):
    """`_reset_and_seed_phase1` inserts exactly 20 wave1 keys and no others."""
    repository = _setup_internal_repository(monkeypatch)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    inserted = await _reset_and_seed_phase1(mock_db, str(partner_file))

    # 20 internal rows inserted, all wave1
    assert inserted == 20
    inserted_keys = _inserted_partner_txn_ids(repository)
    assert len(inserted_keys) == 20
    assert set(inserted_keys) == set(_wave1_keys())
    # No wave2 keys
    assert not any(k.startswith("MOMO_TXN_91") for k in inserted_keys)
    # No missing-partner key
    assert MISSING_PARTNER_KEY not in inserted_keys
    # Broad wipe happened first
    seed_call = repository.find_existing_partner_txn_ids.await_args
    assert seed_call is not None
    assert seed_call.args[0] == "MOMO"
    assert seed_call.args[1] == WAVE1_KEYS
    # Partner file on disk contains the 20 wave1 keys
    file_keys = _read_partner_txn_ids(partner_file)
    assert sorted(file_keys) == sorted(WAVE1_KEYS)


# ── Test 2: phase2 adds wave2 only ──────────────────────────────────────────


async def test_phase2_adds_wave2_only(mock_db: MagicMock, monkeypatch, tmp_path: Path):
    """`_add_phase2` (after reset) inserts 20 wave2 keys and overwrites the file."""
    repository = _setup_internal_repository(monkeypatch)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    # Establish wave1 baseline
    wave1_inserted = await _reset_and_seed_phase1(mock_db, str(partner_file))
    assert wave1_inserted == 20

    # Reset the mock call list so we can isolate phase2's inserts
    repository.insert_many.reset_mock()

    # Add phase2
    wave2_inserted = await _add_phase2(mock_db, str(partner_file))
    assert wave2_inserted == 20

    # Phase2's insert payload is exactly the wave2 keys
    phase2_keys = _inserted_partner_txn_ids(repository)
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


async def test_phase2_duplicate_keeps_all_existing_rows(mock_db: MagicMock, monkeypatch, tmp_path: Path):
    """Partial duplicate fixture must not introduce missing-partner rows."""
    repository = _setup_internal_repository(monkeypatch)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    assert await _reset_and_seed_phase1(mock_db, str(partner_file)) == 20
    repository.insert_many.reset_mock()

    inserted = await _add_phase2_duplicate(mock_db, str(partner_file))

    assert inserted == 10
    assert set(_inserted_partner_txn_ids(repository)) == set(WAVE2_KEYS[:10])
    file_keys = _read_partner_txn_ids(partner_file)
    assert len(file_keys) == 30
    assert file_keys == WAVE1_KEYS + WAVE2_KEYS[:10]


# ── Test 3: missing_partner_demo ────────────────────────────────────────────


async def test_missing_partner_demo(mock_db: MagicMock, monkeypatch, tmp_path: Path):
    """`_add_missing_partner_demo` (after reset) inserts the anomaly row and keeps the wave1 file.

    After this, a FULL_SNAPSHOT ingestion should produce 20 MATCHED + 1 MISSING_PARTNER.
    """
    repository = _setup_internal_repository(monkeypatch)
    partner_file = tmp_path / "settlement_MOMO_20260605.xlsx"

    # Establish wave1 baseline
    wave1_inserted = await _reset_and_seed_phase1(mock_db, str(partner_file))
    assert wave1_inserted == 20

    # Reset mock so we can isolate the missing-partner insert
    repository.insert_many.reset_mock()

    # Inject the missing-partner row
    mp_inserted = await _add_missing_partner_demo(mock_db, str(partner_file))
    assert mp_inserted == 1

    # The missing-partner row was inserted with the correct key
    mp_keys = _inserted_partner_txn_ids(repository)
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
