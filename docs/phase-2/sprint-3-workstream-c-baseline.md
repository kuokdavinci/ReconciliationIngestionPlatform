# Sprint 3 — Workstream C full-dataset v2 baseline

## Run metadata

| Field | Value |
|---|---|
| Run date | 2026-08-26 |
| Boundary | `IngestionPipeline.process_file` |
| Dataset | `data/eda/fraud_detection/raw/Fraud Detection Dataset.csv` |
| Dataset SHA-256 | `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6` |
| Mapping version | `sprint3-fraud-detection-v2` |
| Database | Docker-backed MongoDB/PostgreSQL; benchmark database `reconciliation` |
| Batch/write configuration | `batch_size=20,000`, `write_workers=1`, `ordered_insert=false`, `fast_mode=false` |
| Cleanup | Benchmark records and temporary mapping removed |

## Result

| Input | Persisted | Rejected/failed | Duplicate | Quarantined | Quality | Runtime outcome | Elapsed | Throughput |
|---:|---:|---:|---:|---:|---|---|---:|---:|
| 1,000,000 | 1,000,000 | 0 | 0 | 0 | `PASS` | `CONTINUE / INGESTED` | 125.588s | 7,962.5 rows/s |

The quality counters were:

```json
{
  "inputRows": 1000000,
  "persistedRows": 1000000,
  "rejectedRows": 0,
  "duplicateRows": 0,
  "failedRows": 0,
  "persistenceFailedRows": 0,
  "quarantinedRows": 0
}
```

## Stage timing

The runtime log reported approximately `125.588s` total ingestion time:

| Stage | Time |
|---|---:|
| Parse | 9.997s |
| Normalize/build | 25.169s |
| Validate | 3.225s |
| Database insert window | 123.833s |
| Post-insert update | 0.004s |
| Batch write operations | 52 |

The stage values are cumulative runtime instrumentation and are not additive;
the database insert window overlaps the overall pipeline wall-clock boundary.

## Interpretation and limits

The run proves that the v2 mapping can process the complete frozen dataset
through normalization, validation and persistence with no rejected rows,
duplicates or quarantine records. Source `timestamp` maps to required
`transDate`; the benchmark persists canonical values through the existing UTC
boundary. `fraud_type` remains intentionally unmapped.

This run does not prove reconciliation correctness, conflicting-duplicate
handling, invalid-row quarantine, Airflow acceptance, or statistical/fraud
semantics. Those require separate fixtures or explicit business contracts.

## Reproduction

With MongoDB and PostgreSQL available through the project Compose environment:

```bash
uv run python scripts/benchmark_fraud_detection.py --full-only
```

The runner writes the JSON and Markdown artifacts, then removes benchmark
records and the temporary mapping in its `finally` cleanup path.
