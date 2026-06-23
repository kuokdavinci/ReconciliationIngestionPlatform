# Plan: Batch Size & Parallel Execution Optimization

**Quick ID:** 260623-mve
**Mode:** quick

## Tasks

### Task 1: Fix hardcoded 100k defaults in scheduler and review_packet_actions

**Files:** `src/scheduler/jobs.py`, `src/services/review_packet_actions.py`

**Action:**
- `scheduler/jobs.py:326`: Change `batch_size: int = 100000` to `batch_size: int | None = None` and pass `batch_size=settings.ingest_batch_size` when creating IngestionPipeline
- `services/review_packet_actions.py:408`: Change `batch_size=100000` to use `settings.ingest_batch_size`

**Verify:** grep for hardcoded 100k in these files — zero matches for `batch_size.*=.*100000`

### Task 2: Make PARTNER_BATCH_SIZE configurable in ReconciliationEngine

**Files:** `src/reconciliation/engine.py`, `src/config/settings.py`

**Action:**
- Add `recon_partner_batch_size: int = 10000` to Settings in `settings.py`
- Add `result_batch_size: int | None = None` parameter to `ReconciliationEngine.__init__` (already exists — keep)
- Add `partner_batch_size: int | None = None` parameter, default from `settings.recon_partner_batch_size`
- Rename class constant usage `self.PARTNER_BATCH_SIZE` → `self._partner_batch_size` (instance attr from constructor param)
- Keep `PARTNER_BATCH_SIZE` class constant as 100000 for backward compat but use `self._partner_batch_size` everywhere internally
- Update `RESULT_WRITE_BATCH_SIZE` similarly — route to `self._result_batch_size` (already instance based)

**Verify:** All internal references use `self._partner_batch_size` and `self._result_batch_size`

### Task 3: Add correctness tests for parallel batch writes

**Files:** `tests/test_reconciliation.py`, `tests/test_ingestion_pipeline.py`

**Action:**
Add tests proving:
1. total inserted partner records unchanged with parallel workers
2. total reconciliation results unchanged
3. matched count, amount mismatch, status mismatch, unmatched counts correct
4. no duplicate reconciliation results created by parallel writes
5. retry/failure of one batch doesn't corrupt the whole run

**Verify:** `cd /home/kuokdavinci/AdapterService && python -m pytest tests/test_reconciliation.py::test_name -x -v` or similar

### Task 4: Create parallel benchmark script

**Files:** `scripts/batch_parallel_benchmark.py`

**Action:**
Create a benchmark that:
- Tests batch sizes: [5000, 10000, 20000, 50000, 100000]
- Tests worker counts: [1, 2, 4]
- Tests ordered: [true, false]
- Measures: total runtime, records/sec, db_insert_ms, result_bulk_write_ms, average batch time, slowest batch time, error count, duplicate count, inserted count, result count correctness
- Prints compact matrix
- Uses bounded concurrency, reuses existing DB client
- Does not modify production defaults

**Verify:** `python scripts/batch_parallel_benchmark.py --dry-run` to validate it parses correctly

### Task 5: Add env vars and .env.example

**Files:** `.env.example`

**Action:**
Add new env vars:
- `APP_RECON_PARTNER_BATCH_SIZE=10000`

**Verify:** file contains the new entries
