# Sprint 3 — Data Quality and Quarantine Index

Sprint 3 adds deterministic quality decisions to the ingestion runtime and
routes data that cannot be safely persisted into a bounded quarantine
lifecycle. The sprint is split by ownership: Workstream B owns quality gates
and duplicate classification, Workstream C owns normalization/validation, and
Workstream D owns quarantine resolution and source-unit recovery.

## 1. Status and boundary

| Workstream | Scope | Current status | Primary evidence |
|---|---|---|---|
| A | EDA, provenance, frozen baseline and controlled mutations | Implemented | [EDA review](sprint-3-eda-review.md) |
| B | Quality contract, file/row gates, duplicate classification and bounded runtime outcome | Implemented | [Quality contract](sprint-3-workstream-b-quality-contract.md) |
| C | Timestamp normalization, validation parity and v2 source mapping | Implemented; full-dataset v2 evidence captured | [Normalization contract](sprint-3-workstream-c-normalization-validation.md) |
| D | Quarantine persistence, operator resolution, audit, retention and source-unit resume | Implemented at contract/application level; production acceptance pending | [Quarantine lifecycle](sprint-3-data-quality.md#d--quarantine-lifecycle--implemented) |
| E | Operator ownership, approval and escalation workflow | Handoff | [Sprint 3 overview](sprint-3-data-quality.md#e--operator-and-approval-flow) |
| F | Observability, partner sign-off and production acceptance | Handoff | [Sprint 3 overview](sprint-3-data-quality.md#f--observability-and-production-acceptance) |

This sprint does not promote fraud labels, amount outliers, entity
consistency, coordinates or temporal volume into automatic rejection. Those
remain partner/business or monitoring contracts.

## 2. Core runtime flow

```text
source file / API unit
  → mapping and configuration preparation
  → deterministic file quality gate
  → normalize source row
  → validate canonical row
  → batch persistence and duplicate classification
      ├─ PASS / CONTINUE → persist, reconcile, advance checkpoint, cleanup
      ├─ row REJECT      → quarantine the rejected row, continue valid rows
      ├─ CONFLICT        → quarantine fingerprints, hold the source unit
      └─ BATCH_FATAL     → fail before row persistence
  → operator/worker resolution
  → source-unit resume after all active blockers are terminal
```

## 3. Ownership map

| Layer | Workstream B | Workstream C | Workstream D |
|---|---|---|---|
| Domain | Rule codes, phases, decisions, violations and bounded aggregation | Timestamp parsing and canonical date contract | Quarantine states, actions, transitions and retention policy |
| Application | File/row quality policy and bounded Airflow result | Normalizer/validator parity and mapping behavior | Claim, replay, correction, accept-existing, reject and resume |
| Persistence | Atomic PostgreSQL write and fingerprint comparison | UTC persistence boundary | Mongo quarantine records, raw-page/source-row readers and indexes |
| Runtime | `CONTINUE`, `HOLD_FOR_REVIEW`, `FAIL` | Canonical `transDate` and structured `INVALID_TIMESTAMP` | Source-unit blocker guard and checkpoint-driven recovery |

## 4. Deterministic contracts

### Quality and accounting

- `BATCH_FATAL` stops before row processing.
- Ordinary row rejects are quarantined while valid rows continue.
- Equivalent duplicates are counted and skipped without quarantine.
- Conflicting duplicates retain incoming/existing fingerprints and hold the
  source unit.
- For a completed source unit:

  ```text
  inputRows = persistedRows + rejectedRows + duplicateRows + persistenceFailedRows
  ```

- Bounded Airflow/runtime results contain counters and rule codes, not raw rows
  or unbounded error evidence.

### Normalization and validation

- Source `timestamp` maps to required canonical `transDate`.
- ISO `Z`, offset timestamps and fractional seconds normalize to UTC-aware
  values.
- Four legacy date formats remain supported as naive values.
- Invalid timestamps produce structured `INVALID_TIMESTAMP` evidence without
  exposing the raw value.
- Normal and fast paths share canonical business outcomes and error evidence.
- PostgreSQL receives aware timestamps through the existing UTC-naive mapper.

### Quarantine and recovery

- `PENDING → REPROCESSING → PENDING|RESOLVED|REJECTED` is the only valid
  lifecycle.
- Claims are atomic and lease/actor-bound.
- Replay uses authoritative source-file or staged raw-page data; corrected rows
  are explicit operator input.
- `ACCEPT_EXISTING` requires matching `existingFingerprint`.
- A source unit resumes only when no active conflicting-duplicate blocker
  remains; checkpoint advancement precedes raw-page/file cleanup.

## 5. Runtime outcomes

| Outcome | Meaning |
|---|---|
| `PASS / CONTINUE / INGESTED` | All rows were accepted and the source unit can complete normally. |
| `REVIEW / CONTINUE` | Some ordinary rows were rejected/quarantined; valid rows continue. |
| `REVIEW / HOLD_FOR_REVIEW` | A conflicting duplicate requires resolution before checkpoint progress. |
| `FAIL` | Structural/configuration quality failure; do not retry as infrastructure failure. |
| `RESOLVED` | A quarantine row was corrected, replayed successfully, or accepted as equivalent/existing. |
| `REJECTED` | An operator explicitly discarded the row with a reason. |
| `PENDING` | Resolution failed deterministically or through retryable infrastructure failure and can be attempted again. |

## 6. Canonical implementation map

| Capability | Module |
|---|---|
| Quality domain contract | [`src/domain/ingestion/quality.py`](../../src/domain/ingestion/quality.py) |
| Quality policy and bounded result | [`src/application/ingestion/quality_policy.py`](../../src/application/ingestion/quality_policy.py), [`contracts.py`](../../src/application/ingestion/contracts.py) |
| File quality gate | [`src/pipeline/quality_gate.py`](../../src/pipeline/quality_gate.py) |
| Duplicate classification and persistence | [`src/domain/partner_transaction/duplicates.py`](../../src/domain/partner_transaction/duplicates.py), [`repository.py`](../../src/infrastructure/partner_transaction/repository.py) |
| Timestamp contract | [`src/normalizer/timestamps.py`](../../src/normalizer/timestamps.py), [`normalizer.py`](../../src/normalizer/normalizer.py), [`validator.py`](../../src/validators/validator.py) |
| C benchmark runner | [`scripts/benchmark_fraud_detection.py`](../../scripts/benchmark_fraud_detection.py) |
| Quarantine domain and persistence | [`src/domain/ingestion/quarantine.py`](../../src/domain/ingestion/quarantine.py), [`quarantine_repository.py`](../../src/infrastructure/ingestion/quarantine_repository.py) |
| Quarantine resolution | [`quarantine_service.py`](../../src/application/ingestion/quarantine_service.py), [`quarantine_reprocessing.py`](../../src/application/ingestion/quarantine_reprocessing.py) |
| Source-unit resume | [`source_unit_orchestrator.py`](../../src/application/ingestion/source_unit_orchestrator.py), [`source_unit_resume.py`](../../src/application/ingestion/source_unit_resume.py) |
| Quarantine API | [`src/api/quarantine.py`](../../src/api/quarantine.py) |

## 7. Evidence and commands

### Workstream C focused contract tests

The current focused run is `242 passed`:

```bash
uv run pytest \
  tests/test_timestamp_normalization.py \
  tests/test_normalizer.py \
  tests/test_validator.py \
  tests/test_persistence_time.py \
  tests/test_persistence_mappers.py \
  tests/test_quality_contract.py \
  tests/test_ingestion_pipeline.py \
  tests/test_benchmark_fraud_detection.py \
  tests/test_benchmark_quality_contract.py \
  tests/test_api_review_packets.py::test_runtime_timestamp_code_does_not_parse_reason \
  tests/test_api_review_packets.py::test_run_runtime_validation_returns_high_risk_for_failed_validation \
  -v --tb=short
```

### Workstream C full-dataset v2 evidence

The 1M-row raw dataset was run through the real Docker-backed ingestion
boundary on 2026-08-26. The sanitized result is recorded in
[the baseline report](sprint-3-workstream-c-baseline.md) and the machine-readable
[benchmark artifact](../../data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json).

| Input | Persisted | Failed | Duplicate | Quarantined | Outcome | Throughput |
|---:|---:|---:|---:|---:|---|---:|
| 1,000,000 | 1,000,000 | 0 | 0 | 0 | `PASS / CONTINUE / INGESTED` | 7,962.5 rows/s |

The benchmark elapsed time was `125.588s`; benchmark records and mapping were
removed after the run. This is ingestion-boundary evidence, not reconciliation,
statistical or partner-acceptance evidence.

### Workstream B and D gates

- [Workstream B quality/performance evidence](sprint-3-workstream-b-quality-contract.md#acceptance-and-performance-evidence)
- [Workstream D focused lifecycle gate](../CI-MAP.md#workstream-d--quarantine-lifecycle)
- [Workstream C normalization contract and evidence](sprint-3-workstream-c-normalization-validation.md)

## 8. Handoffs and acceptance boundary

Workstream C and the core B/D contracts are implemented. Remaining Sprint 3
acceptance work is operator ownership/escalation, repeated live environment
evidence, dashboards/alerts, partner sign-off and production cutover. Sprint 4
owns the broader observability expansion.
