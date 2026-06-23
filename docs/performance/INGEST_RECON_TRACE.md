# Performance Tracing Report: Ingestion & Reconciliation Pipeline

This document captures the performance tracing implementation, baseline measurements, diagnosed bottlenecks, optimizations applied, and results for the 100k records benchmark.

## 1. Baseline Performance & Bottlenecks

### Baseline Timing (Before Optimizations)
Before adding performance tracing and applying optimizations, the pipeline exhibited the following characteristics:
* **Ingestion (100k ZALOPAY rows):** ~30.0 seconds (3,331 records/sec)
* **Reconciliation (100k matched rows):** ~20.5 seconds (4,870 records/sec)

### Diagnosed Bottlenecks
Through the newly introduced structured tracing logs (`PERF_INGEST` and `PERF_RECON`), we traced the exact bottlenecks:

1. **Excel Parsing XML / String Match Overhead (Ingestion):**
   * *Evidence:* `read_file_ms` (workbook load) took ~15.5 seconds, and `parse_rows_ms` took ~4.5 seconds.
   * *Cause:* Openpyxl's pure-Python read-only parser was CPU-bound and slow. Additionally, it was checking every cell across 40 columns for footer/summary keywords.
   
2. **Pydantic Serialization/Deserialization Overhead (Reconciliation):**
   * *Evidence:* `unmatched_detection_ms` took ~6.5 seconds and `result_bulk_write_ms` took ~10.7 seconds.
   * *Cause:* Generating and serializing 100,000 `ReconciliationResult` Pydantic models via `.model_dump()` and recursive type conversion (`_convert_special_types`) inside the repository helper generated massive CPU overhead during database writes.

3. **Wrong/Mismatched Lookup Key (Reconciliation):**
   * *Evidence:* `matched_count` was initially 0, treating all 100k rows as missing partner/internal records.
   * *Cause:* Mapped key config deviation. ZALOPAY Excel mapping associated column 11 (`zpMaHDon`) with `trace` while internal transactions used `zpTransId` as their matching key. This caused the engine lookup to fail, triggering large CPU loops building unmatched arrays.

---

## 2. Optimizations Applied

### A. Summary Pattern Search Optimization in Excel Reader
* Restrained summary/footer check to only the first 3 columns of each row (`row[:3]`), as summary markers like "Total" or "Footer" never reside in the 40th column.
* Pre-compiled all skip patterns into lowercase during reader initialization to avoid repeating `.lower()` inside nested cell-level loops.
* **Impact:** Reduced overall CPU comparison operations by over 90% in the parse stage.

### B. MongoDB Bulk Write bypass of Pydantic Validation (Fast Mode)
* Added a `fast_mode` toggle to the `ReconciliationEngine`.
* When `fast_mode` is enabled (activated in production API triggers, scheduler jobs, and approve reprocessing flows):
  * The engine collects raw Python dictionaries representing the results instead of instantiating `ReconciliationResult` Pydantic objects.
  * Writes to MongoDB bypass `BaseRepository.insert_many` model dump loops and go directly to `collection.insert_many()` after converting Decimal values.
* **Impact:** Reduced CPU serialization and bulk write time by ~50%.

### C. Matching Key Alignment for ZALOPAY Config
* Modified the seeded ZALOPAY mapping config to map `zpMaHDon` to `extra.zpMaHDon` instead of `trace`.
* This left the `trace` field empty (`None`), prompting `_resolve_partner_txn_id` to fall back on `pd.id` (`zpTransId`), aligning it perfectly with internal transactions.
* **Impact:** Successfully matched all 99,989 transactions and eliminated unmatched Pydantic generation paths.

### D. Migration to Rust-Backed Calamine Excel Parser
* Replaced the pure-Python `openpyxl` library with `python-calamine` (an extremely fast Excel parser written in Rust).
* Re-implemented `ExcelStreamReader` methods to support Calamine's worksheets, ensuring a helper cleans cells (`''` mapped to `None`, and whole floats to `int` for monetary and ID values).
* **Impact:** Reduced Excel load time (`read_file_ms`) from ~15.5 seconds to just ~1.07 seconds (14.5x faster).

---

## 3. Performance Comparison Table

| Stage | Records | Before (Baseline) | After (Optimized) | Improvement | Records/sec Before | Records/sec After |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ingestion Pipeline** | 99,997 | 30.013s | 14.359s | **+52.1%** | 3,331.7 rec/s | 6,916.3 rec/s |
| **Reconciliation Engine** | 100,004 | 20.720s | 13.436s | **+35.1%** | 4,826.4 rec/s | 7,342.5 rec/s |

---

## 4. Remaining Risks & Future Work
* **Network & Database Write Limitations:** DB write operations (`db_insert_ms`) now represent the largest portion of ingestion time (~5.3 seconds). This is bounded by local MongoDB disk/write speed.
* **High Column Width Overhead:** Files with more than 50 columns will still experience parsing overhead. Keeping spreadsheet structures clean is recommended.

