# Sprint 3 — Index

Sprint 3 turns the Fraud Detection Dataset EDA handoff into an explicit
runtime quality contract. The work is split into Workstreams A–F so that
deterministic ingestion rules stay separate from quarantine operations,
operator workflow, and observability.

## Status at a glance

| Workstream | Scope | Status |
|---|---|---|
| A | EDA, provenance, frozen profile, controlled mutations, rule handoff | Implemented |
| B | Quality rules, duplicate classification, conflict quarantine, bounded result | Implemented |
| C | Timezone-aware `transDate` normalization and structured validation errors | Implemented; full-dataset v2 evidence pending |
| D | Quarantine retention, resolution, and reprocessing | Handoff |
| E | Operator ownership and approval flow | Handoff |
| F | Observability and production acceptance | Handoff |

## Canonical documents

| Document | Purpose |
|---|---|
| [`sprint-3-data-quality.md`](sprint-3-data-quality.md) | Overall scope, non-goals, frozen source schema, and A–F boundaries |
| [`sprint-3-workstream-summary.md`](sprint-3-workstream-summary.md) | Workstream A decision matrix and EDA-to-runtime handoff |
| [`sprint-3-eda-review.md`](sprint-3-eda-review.md) | Dataset provenance, EDA findings, and rule-promotion rationale |
| [`sprint-3-workstream-b-quality-contract.md`](sprint-3-workstream-b-quality-contract.md) | Deterministic quality contract, duplicate outcomes, and bounded source-unit result |
| [`sprint-3-workstream-c-normalization-validation.md`](sprint-3-workstream-c-normalization-validation.md) | Timestamp parser, validation error contract, parity, persistence boundary, and verification evidence |

The Workstream C evidence document is the canonical source for the current
`timestamp → transDate` behavior. The A documents retain the historical EDA
and frozen-baseline context and must not be read as a second runtime mapping.

## Frozen dataset and pending v2 artifact

The Workstream A profile remains frozen at version `3` with SHA-256
`e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6`.

Workstream C code and generated-fixture verification are complete. The raw
1M-row CSV is now present locally at
`data/eda/fraud_detection/raw/Fraud Detection Dataset.csv` and matches the
frozen checksum. The external v2 evidence is still pending because the
benchmark has not yet produced its report artifacts. Run the benchmark and add
both outputs:

- `data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json`
- `docs/phase-2/sprint-3-workstream-c-baseline.md`

The v2 artifact must use mapping version `sprint3-fraud-detection-v2`, preserve
the frozen profile checksum, contain no MongoDB URI or credentials, and report
the actual measured throughput. Do not edit the frozen Workstream A profile or
the historical v1 benchmark outputs.

## Verification snapshot

- Focused Workstream C suite: `301 passed`.
- Backend suite excluding environment-gated analysis, ingestion integration,
  and seed tests: `1,270 passed, 6 skipped`.
- PostgreSQL integration/migration suite: `16 passed`.
- Raw dataset available locally: `167.4M`, SHA-256 matches the frozen profile.
- Ruff, Mypy, and `git diff --check`: passed.
- Workstream B clean-path performance evidence remains within the accepted
  regression threshold; timestamp parsing is not on partners without a
  `transDate` mapping.

## Scope guardrails

Keep amount IQR, fraud semantics, entity consistency, coordinate semantics,
temporal volume, and timestamp precision drift outside automatic rejection
until a partner contract promotes them. Do not add database schema changes,
repository lookups, raw rows, complete errors, parsed timestamps, or
credentials to the bounded Airflow/source-unit result.

Workstream D owns quarantine retention, operator resolution, and reprocessing
for already-routed rejects and conflicting duplicates.
