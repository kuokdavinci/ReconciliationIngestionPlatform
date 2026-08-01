# Sprint 1 Report — Idempotency & Duplicate Prevention

> **Branch:** `phase2/sprint-1`
> **Scope:** file replay, fetch-unit replay, transaction deduplication and conflict-safe persistence
> **Status:** Implemented. The recorded benchmark artifact reports 13/13 scenarios passed; a clean runtime re-validation is still required in an environment with database services and available Python package resolution.

## Summary

Sprint 1 adds idempotency boundaries to ingestion:

- Atomic file claims by `fileHash` and fetch-unit claims by `fetchUnitKey`.
- PostgreSQL partner transactions with required `ingestion_key`, unique per `(identify, ingestion_key)`.
- Batch insertion using `ON CONFLICT DO NOTHING`, with `inserted`, `duplicates` and `failed` statistics.
- Deterministic key derivation; payloads without a usable identifier are rejected.
- MOMO E2E seeding for the partial-duplicate case: 20 existing rows plus 10 new rows.

Incremental recovery, data-quality quarantine and observability remain later Phase 2 work.

## Reviewed implementation

| Area | Components | Result |
|---|---|---|
| Schema | `alembic/versions/0002_ingestion_idempotency.py` | Adds `ingestion_key` and the PostgreSQL uniqueness contract. |
| Persistence | `src/models/postgres.py`, `src/models/data_container.py` | PostgreSQL transaction repository and conflict-safe batch writes. |
| Claims | `src/models/reconciliation_file.py`, `src/models/indexes.py` | Atomic file/fetch-unit create-or-get behavior. |
| Pipeline | `src/pipeline/ingestion_pipeline.py`, `src/core/types.py` | Key derivation, replay handling and detailed statistics. |
| Runtime | `src/fetchers/*`, `src/scheduler/jobs.py`, `src/api/automation.py` | Propagates idempotency metadata and exposes duplicate outcomes. |
| E2E | `scripts/seeding/seed_momo_e2e.py`, `tests/test_sprint1_eval_benchmark.py` | Seed helpers and the Sprint 1 evaluation suite. |

## Idempotency contract

File replay is stopped by the canonical `fileHash` claim. API page replay is stopped by `fetchUnitKey`, even when the payload or file name differs. The canonical existing record is returned for a replay.

For transactions, the pipeline derives a stable `ingestion_key` from the partner identifier contract. It raises `ValueError` when no identifier is available; it does not create a random fallback key. PostgreSQL enforces uniqueness per partner using `(identify, ingestion_key)`.

Batch conflicts are ignored at the database boundary and counted as duplicates rather than failing the entire batch.

## Function-level implementation map

| Function | Responsibility in the idempotency contract |
|---|---|
| `IngestionPipeline._compute_file_hash()` | Computes the stable SHA-256 identity used for file replay protection. |
| `IngestionPipeline._derive_fetch_unit_key()` | Validates and derives the stable identity for an API page, cursor or fetch window. |
| `IngestionPipeline._derive_ingestion_key()` | Derives the transaction identity and rejects payloads without a usable identifier. |
| `IngestionPipeline.process_file()` | Coordinates claim, parse, key derivation, batch persistence, duplicate accounting, status updates and failure handling. |
| `ReconciliationFileRepository.create_or_get_by_file_hash()` | Atomically creates the canonical file claim or returns the existing file/fetch-unit record after a replay race. |
| `ReconciliationFileRepository.find_by_file_hash()` | Looks up the canonical file claim by SHA-256. |
| `ReconciliationFileRepository.find_by_fetch_unit_key()` | Looks up the canonical claim for an API fetch unit. |
| `DataContainerRepository.insert_many()` | Persists partner transactions with PostgreSQL `ON CONFLICT DO NOTHING` and returns inserted/duplicate counts. |
| `IngestionPipeline._record_batch_result()` | Aggregates `inserted`, `duplicates` and `failed` results without converting duplicates into batch failures. |
| `DataContainerRepository.rebind_source_file_by_ingestion_keys()` | Rebinds existing transaction rows to the current logical file after a partial duplicate replay. |
| `scheduler.jobs._fetch_unit_metadata()` | Carries source endpoint/page/cursor/window identity from scheduler to ingestion. |
| `scheduler.jobs.run_fetch_config_once()` and `_run_ingestion()` | Pass the fetch-unit context into the pipeline and persist duplicate outcomes for operational reporting. |

## MOMO demo

```bash
make momo-e2e-reset
make momo-e2e-run
make momo-e2e-phase2
make momo-e2e-run
```

For the explicit partial-duplicate setup:

```bash
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py phase2_duplicate
```

The second file contains 20 old rows and 10 new rows. The expected result is 10 inserted, 20 skipped as duplicates, and no duplicate transaction rows. These commands delete demo data by partner and must only be run against a test/demo environment.

## Evidence

- [Benchmark specification](sprint-1-eval-benchmark.md)
- [Recorded benchmark run](sprint-1-eval-benchmark-run.md)
- [Implementation notes](sprint-1-idempotency.md)

The recorded run covers schema, initial insert, file replay, partial/full conflict, duplicate invariants, deterministic key validation, migration safety, PostgreSQL transaction storage, concurrent file claim and fetch-unit replay.

## Current validation

| Check | Result | Notes |
|---|---|---|
| Branch and working tree | PASS | `phase2/sprint-1`; clean before documentation edits. |
| Sprint benchmark | PASS | Chạy với workspace-local `UV_CACHE_DIR` và Docker PostgreSQL/Mongo; `1 passed in 0.68s`, dùng database `reconciliation_test`. |
| Documentation | Updated | Claims now match the actual migration name, scope, demo data and validation state. |

Re-run after restoring package access and database services:

```bash
UV_CACHE_DIR=$PWD/.uv-cache uv run python -m pytest tests/test_sprint1_eval_benchmark.py -q
```

## Review conclusion

The Sprint 1 implementation uses database constraints as the final duplicate-safety boundary and separates file, fetch-unit and transaction identity. The benchmark has been re-validated successfully against Docker PostgreSQL/Mongo using `reconciliation_test`.
