# Sprint 3 — Workstream C: Normalization and validation contract

**Evidence status:** `implemented; full-dataset v2 evidence pending`

## Scope and non-goals

Workstream C promotes the frozen Fraud Detection Dataset source timestamp into
canonical `transDate`, defines bounded structured timestamp errors, and proves
the same timestamp contract in normal and fast ingestion modes. It preserves
the existing Decimal, required-field, duplicate, and quality-policy behavior.

Timestamp timezone absence is not a new global runtime rejection rule. Amount
IQR, fraud semantics, entity/location/coordinate consistency, temporal volume,
and timestamp precision remain outside automatic rejection. This work does not
change Airflow payloads, duplicate identity/fingerprints, quarantine lifecycle,
quality precedence, PostgreSQL schema, or reconciliation behavior.

## Timestamp input and canonicalization matrix

| Source input | Canonical result |
|---|---|
| Extended ISO timestamp `YYYY-MM-DDTHH:MM:SSZ` | Accepted as an aware `datetime`, normalized to UTC |
| Extended ISO timestamp `YYYY-MM-DDTHH:MM:SS±HH:MM` | Accepted as an aware `datetime`, normalized to the equivalent UTC instant |
| Extended ISO timestamp with 1–6 fractional digits and an offset | Accepted; microsecond precision is preserved while normalizing to UTC |
| `YYYY-MM-DD` | Accepted as a legacy naive `datetime` |
| `DD/MM/YYYY` | Accepted as a legacy naive `datetime` |
| `YYYY-MM-DD HH:MM:SS` | Accepted as a legacy naive `datetime` |
| `DD/MM/YYYY HH:MM:SS` | Accepted as a legacy naive `datetime` |
| Naive `datetime` object | Accepted without assigning or reinterpreting a timezone |

Padded values, empty strings, malformed or impossible dates, naive ISO values
using `T`, and offset-bearing forms outside this strict extended-calendar
grammar reject deterministically. The benchmark v2 mapping sends source column
2 (`timestamp`) to required canonical `transDate`; the obsolete
`extra.sourceTimestamp` interpretation is no longer active.

## Structured validation error contract

An invalid source timestamp produces
`INVALID_TIMESTAMP / NORMALIZATION / ERROR / REJECT`. Its bounded `actual`
evidence contains `type` only and never includes the raw timestamp input. A
defensive non-`datetime` value already present in canonical `transDate` uses the
same `INVALID_TIMESTAMP / ERROR / REJECT` rule in the `VALIDATION` phase.

Review Runtime preserves its legacy `INVALID_DATE` presentation code by
mapping from the structured ingestion rule code. It does not parse the human
reason string.

## Normal and fast-path parity

Normal and fast modes produce identical canonical business timestamps, quality
outcomes, and serialized error evidence. An invalid timestamp remains a row
rejection while aggregate quality/orchestration handling remains governed by
the existing policy; timezone absence was not promoted into a global rule.

## Decimal and required-field non-regression

Required ID, amount, currency, status, and mapping-required timestamp behavior
remains unchanged. Decimal strings remain supported; zero remains valid;
negative amounts retain the existing rejection rule; floats and non-finite
amounts reject through the existing invalid-amount boundary. Duplicate
classification and deterministic quality decision precedence are unchanged.

## Persistence timezone convention

Canonical aware timestamps are normalized to UTC. PostgreSQL receives UTC-naive
values only through the existing `as_utc_naive()` mapper. That boundary removes
timezone information exactly once; legacy naive values are passed through and
are not reinterpreted as belonging to a timezone.

## Generated fixture coverage

Tests generate deterministic CSV fixtures in temporary directories rather
than committing or depending on raw source rows. Coverage includes `Z`,
positive and negative offsets, microseconds, all four legacy naive formats,
naive `datetime` objects, malformed/empty/unsupported timestamp inputs,
normal/fast parity, PostgreSQL mapping, Decimal boundaries, required fields,
duplicates, and quality decisions. No raw source row or unbounded error payload
is added to runtime or documentation evidence.

## Performance evidence

Verification date: 2026-08-25.

| Evidence | Required result | Artifact/status |
|---|---|---|
| Focused C tests | Pass | `uv run pytest tests/test_timestamp_normalization.py tests/test_normalizer.py tests/test_validator.py tests/test_persistence_time.py tests/test_persistence_mappers.py tests/test_quality_contract.py tests/test_ingestion_pipeline.py tests/test_benchmark_fraud_detection.py tests/test_benchmark_quality_contract.py tests/test_api_review_packets.py::test_runtime_timestamp_code_does_not_parse_reason tests/test_api_review_packets.py::test_run_runtime_validation_returns_high_risk_for_failed_validation -v --tb=short` — 244 passed |
| Backend CI parity | Pass | Python 3.11.15; `uv sync --all-extras --dev`; Alembic upgrade; `ruff check src dags scripts cli`; `mypy src/ --show-error-codes`; exact backend pytest exclusions with `-v --tb=short` — 1,211 passed, 6 skipped on 2026-08-25 |
| Ingestion CI parity | Pass | Python 3.11.15; Alembic upgrade; Ruff over all workflow paths; exact five-file pytest command with `-v --tb=short` — 57 passed on 2026-08-25 |
| Workstream B performance | clean acceptance true | Fresh `/tmp/workstream-c-non-regression.json`, not committed: 10k `2.573746665097812%`, 100k `3.93044804439444%`, 1M `4.115527979760645%`; all accepted, zero clean lookups |
| Generated 20-row smoke | 20/20, zero failed/duplicate, PASS | Config `sprint3-fraud-detection-v2`; 20 input/20 persisted, zero failed/duplicate, `PASS / CONTINUE`, `INGESTED` |
| Full 1M v2 | optional for implemented-pending state | `implemented; full-dataset v2 evidence pending` |

Exact Backend CI parity commands executed:

```bash
uv sync --all-extras --dev
uv run alembic upgrade head
uv run ruff check src dags scripts cli
uv run mypy src/ --show-error-codes
AI_API_KEY=sk-test-fake-key uv run pytest tests/ \
  --ignore=tests/test_analysis_e2e.py \
  --ignore=tests/test_ingestion_integration.py \
  --ignore=tests/test_ingestion_pipeline.py \
  --ignore=tests/test_seed_momo_e2e.py \
  --ignore=tests/test_sprint1_eval_benchmark.py \
  -v --tb=short
```

Exact Ingestion Pipeline CI parity commands executed:

```bash
uv run alembic upgrade head
uv run ruff check \
  src/fetchers \
  src/pipeline \
  src/application/automation \
  src/domain/fetch_config/models.py \
  src/infrastructure/persistence/mongo_indexes.py \
  scripts/demo/scenarios
AI_API_KEY=sk-test-fake-key uv run pytest \
  tests/test_indexes.py \
  tests/test_ingestion_integration.py \
  tests/test_ingestion_pipeline.py \
  tests/test_seed_momo_e2e.py \
  tests/test_sprint1_eval_benchmark.py \
  -v --tb=short
```

The exact performance command used sizes `10000,100000,1000000`, three repeats,
and wrote only to `/tmp`. Its prescribed machine assertions passed. Transient
pytest timings are not used as performance evidence.

## Full-dataset benchmark evidence

`implemented; full-dataset v2 evidence pending`

The frozen raw 1M CSV and the official
`data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json`
artifact are absent in this checkout. Therefore no checksum/count/throughput
claim is made for a successful full-dataset v2 run, and no artifact is linked
as successful evidence. The frozen Workstream A v3 profile, its SHA-256, and
the Workstream B/v1 benchmark artifacts remain unchanged.

## Remaining handoff to Workstream D

Workstream D owns retention, operator resolution, lifecycle evidence, and
reprocessing for already-routed sanitized rejects and conflicting duplicates.
Workstream C does not expand quarantine contents or lifecycle behavior.
