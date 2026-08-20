# Sprint 3 — Workstream B: Quality contract, gate và Airflow-ready outcome

## Scope

Workstream B promotes deterministic ingestion rules into a runtime contract. It
does not change Airflow scheduling/retry policy, add database columns/indexes,
or promote statistical/fraud semantics into automatic rejection.

## Rule registry

| Rule code | Phase | Default outcome | Meaning |
|---|---|---|---|
| `REQUIRED_SCHEMA_PATH` | CONFIGURATION/FILE | `BATCH_FATAL` | A canonical required path is not mapped or has no source reference. |
| `MISSING_REQUIRED_SOURCE_COLUMN` | FILE | `BATCH_FATAL` | A required mapped column/field is not present in the source structure. |
| `SCHEMA_CONFIG_DRIFT` | FILE | `WARNING` or `BATCH_FATAL` | Append-only drift is reviewable; drift that changes the approved shape is fatal. |
| `SOURCE_STRUCTURE_UNREADABLE` | FILE | `BATCH_FATAL` | The source structure cannot be inspected because the file is corrupt, unsupported, or unreadable. |
| `CONFIG_VALIDATION` | CONFIGURATION | `BATCH_FATAL` | Mapping configuration is structurally invalid. |
| `MISSING_REQUIRED_FIELD` | NORMALIZATION/VALIDATION | `REJECT` | A required row value is absent or empty. |
| `MALFORMED_ROW` | NORMALIZATION | `REJECT` | A row cannot be mapped into the canonical shape. |
| `INVALID_AMOUNT` | NORMALIZATION/VALIDATION | `REJECT` | Amount is not a valid Decimal monetary value. |
| `NEGATIVE_AMOUNT` | VALIDATION | `REJECT` | Amount is below zero; zero remains valid. |
| `INVALID_TIMESTAMP` | NORMALIZATION/VALIDATION | `REJECT` | Timestamp cannot satisfy the current deterministic timestamp contract. |
| `INVALID_STATUS` | VALIDATION | `REJECT` | Status is outside the canonical enum. |
| `EQUIVALENT_DUPLICATE` | PERSISTENCE | `EQUIVALENT_DUPLICATE` | Same key and same business payload; no quarantine record. |
| `CONFLICTING_DUPLICATE` | PERSISTENCE | `CONFLICTING_DUPLICATE` | Same key with a different business payload; quarantine and hold. |

The following remain descriptive/partner-contract candidates and are not
promoted: amount IQR/outliers, fraud semantics, card/customer consistency,
merchant/location consistency, coordinate semantics, temporal volume, and
timestamp precision drift. Complete timezone-aware timestamp parsing remains a
Workstream C handoff.

Internal violations use `message` and `code`. Serialized error boundaries use
the existing `field`/`reason` shape and add `errorCode`, `phase`, `severity`,
`outcome`, `expected`, `actual`, `row`, `trace`, and `configVersion` when
available.

## Architectural ownership

The contract is deliberately split by responsibility:

| Layer | Module | Ownership |
|---|---|---|
| Ingestion domain | `src/domain/ingestion/quality.py` | Rule codes, phases, severities, row/file outcomes, decisions, violations, evaluations, and bounded aggregation invariants. |
| Partner-transaction domain | `src/domain/partner_transaction/duplicates.py` | Business-payload fingerprint equivalence, typed duplicate evidence, and `BatchWriteResult`. |
| Application | `src/application/ingestion/quality_policy.py` | Translation from domain decision/evidence into `CONTINUE`, `HOLD_FOR_REVIEW`, or `FAIL`. |
| Application boundary | `src/application/ingestion/contracts.py` | Stable `field`/`reason` error serialization and bounded Airflow result serialization. |
| Pipeline | `src/pipeline/quality_gate.py` | Invocation order and deterministic file-gate execution. |
| Infrastructure | `src/infrastructure/partner_transaction/repository.py` | Atomic PostgreSQL insert, bulk conflict lookup, and adapter mapping into the domain result. |

Quality belongs to the ingestion domain—not `src/core`—because its rule codes,
decision precedence, and violation semantics are ingestion ubiquitous language.
They are shared by configuration, normalization, validation, and persistence,
but do not depend on Airflow, retry policy, transport casing, or PostgreSQL.
Putting these models in `core` would make a domain policy look like a generic
technical utility. Conversely, orchestration actions remain in the application
layer because `HOLD_FOR_REVIEW` and `FAIL` describe workflow policy rather than
data quality itself.

## Decision and orchestration matrix

| Quality decision | Orchestration action | Runtime behavior |
|---|---|---|
| `PASS` | `CONTINUE` | Persist, reconcile, advance checkpoint, and clean up after checkpoint commit. |
| `REVIEW` from ordinary row rejects/warnings | `CONTINUE` | Valid rows continue; rejected rows are quarantined. |
| `REVIEW` with `CONFLICTING_DUPLICATE` | `HOLD_FOR_REVIEW` | Do not reconcile, advance, or clean up the source unit; release its checkpoint for review. |
| `FAIL` from structural/config fatal | `FAIL` | Stop before row processing, mark the file/source unit failed, and do not retry as an infrastructure error. |
| Infrastructure error | Existing retry policy | Keep retryability outside the quality model. |

Aggregation is deterministic: any `BATCH_FATAL` produces `FAIL`; otherwise a
row `REJECT`, `WARNING`, or conflicting duplicate produces `REVIEW`; only
`VALID` and equivalent duplicates produce `PASS`. `topRuleCodes` is bounded to
10 entries.

## File and row gates

`FileQualityGate` runs after configuration preparation and before the reader's
row iterator. It validates required paths, required source columns, mapping
structure, and structure drift. Structure inspection is header-only
(`sample_size=0`), so data rows are not sampled before the gate decides.
Append-only columns produce
`REVIEW/WARNING`; breaking drift and unreadable structure produce
`FAIL/BATCH_FATAL`. A failed gate does not enter row normalization or
persistence. It never mutates mappings. Invalid or missing mapping
configuration is promoted to the same non-retryable quality-fail path rather
than being treated as an infrastructure exception. Only the dedicated source
inspection exception is reclassified as `SOURCE_STRUCTURE_UNREADABLE`;
programming and unrelated runtime exceptions remain on the infrastructure
retry path.

The row gate is the normalizer plus validator. Fast mode runs the same promoted
deterministic rules as normal mode; it only avoids Pydantic construction for
the final repository-ready object.

## Duplicate fingerprint contract

`BatchWriteResult` is the single typed persistence result and every key conflict
must have one typed `DuplicateDetail`. The adapter first performs an atomic CTE
insert/classification. Its temporary stage records `incoming_ordinal` and
orders the insert by that value, so intra-batch conflict evidence refers to the
actual incoming row that lost the conflict. Only when conflicts exist does it
run one bulk payload lookup and calculate SHA-256 fingerprints.

The canonical fingerprint payload contains only:

```text
partner_id
partner_trace
partner_status
normalized Decimal amount
currency
UTC-normalized transDate
canonical sorted partner metadata
```

Database UUIDs, request IDs, source-file IDs, created/modified timestamps, and
persistence-only status are excluded. Decimal formatting and timezone
representations of the same instant therefore hash identically. There is no
per-row existing-record lookup. Equivalent duplicates are counted but do not
create quarantine records. Conflicts retain incoming/existing fingerprints and
source row context in quarantine.

The clean path returns immediately after the atomic insert classification: it
does not build a conflict map, query existing payloads, or calculate a hash.
The conflict map contains only keys that actually conflicted. The adapter
performs at most one existing-payload `SELECT` per batch; the removed row
validator duplicate API cannot reintroduce N+1 lookups.

## Counter invariant

For every completed source unit:

```text
inputRows = persistedRows + rejectedRows + duplicateRows + persistenceFailedRows
```

`duplicateRows` is the total key-conflict count. The runtime additionally
tracks `equivalentDuplicateRows`, `conflictingDuplicateRows`, and
`warningRows`. It emits the explicit `persistenceFailedRows` counter while
retaining the existing `failedRows` boundary field with the same persistence
failure value. `quarantinedRows` is a storage count only and is deliberately
not added to the accounting invariant.

Existing application/persistence fields remain stable:
`ProcessingStats`, `ReconciliationFile.totalRows`, `successRows`,
`failedRows`, `duplicateRows`, `stage_summary.currentStage`, and
`stage_summary.lastError`. Stage summaries now include bounded `quality` data
with `decision`, `action`, `ruleCounts`, `outcomeCounts`, and `topRuleCodes`.

## Airflow source-unit result

The application boundary exposes a bounded result; it does not put raw rows,
the complete error list, or fingerprints into XCom:

```json
{
  "success": true,
  "outcome": "INGESTED",
  "qualityDecision": "REVIEW",
  "orchestrationAction": "HOLD_FOR_REVIEW",
  "qualityCounters": {
    "inputRows": 100,
    "persistedRows": 98,
    "rejectedRows": 1,
    "duplicateRows": 1
  },
  "topRuleCodes": ["CONFLICTING_DUPLICATE"]
}
```

`CONTINUE` completes and advances the checkpoint. `HOLD_FOR_REVIEW` releases
the checkpoint without reconciliation or cleanup. `FAIL` marks the source
unit failed/blocked with retryability disabled. Infrastructure exceptions keep
the existing retry semantics. A quality hold uses the structural checkpoint
reason `quality_review:CONFLICTING_DUPLICATE`; no error-message parsing is used.
The reason does not add raw evidence to XCom.

## Acceptance and performance evidence

Acceptance is defined against clean, exact-duplicate-heavy, and
conflict-heavy batches at 10k, 100k, and 1M rows. Clean data must not perform
an existing-payload lookup; conflict handling is set-based with at most one
bulk payload query per batch and no N+1 query. Clean throughput regression
should remain within roughly 10%, and the Airflow payload must stay bounded by
summary size rather than rejected-row count. Quarantine stores only the rows
that require it.

The reproducible harness is `scripts/benchmark_quality_contract.py`:

```bash
uv run python scripts/benchmark_quality_contract.py \
  --sizes 10000,100000,1000000 \
  --repeats 1 \
  --output /tmp/workstream-b-quality-benchmark.json
```

A verified run on 2026-08-20 used `--sizes 10000 --repeats 1` after the
context-free valid-evaluation optimization and passed the clean-data
acceptance threshold:

| Scenario | Baseline rows/s | Workstream B rows/s | Throughput regression |
|---|---:|---:|---:|
| Clean | 13,739 | 12,987 | 5.47% |
| Equivalent duplicate | 305,286 | 23,233 | 92.39% |
| Conflicting duplicate | 260,267 | 22,821 | 91.23% |

The duplicate scenarios intentionally compare fingerprint work with a baseline
that only constructs a duplicate checksum; they are not used for the clean-data
10% regression gate. They confirm the expected cost of deterministic SHA-256
classification and one conflict lookup per batch.

### Quick-win before/after benchmark — 1M rows

The three repository quick wins were separately compared with the pre-change
implementation using three-repeat median measurements:

| Phase | Baseline | Optimized | Change |
|---|---:|---:|---:|
| Row preparation time | 4.947s | 4.353s | **12.0% faster** |
| Row preparation peak RSS | 1,176,428 KB | 1,168,000 KB | **0.7% lower** |
| Duplicate-row mapping time | 9.987s | 1.133s | **88.7% faster** |
| Duplicate-row mapping peak RSS | 73,172 KB | 70,408 KB | **3.8% lower** |

The row-preparation comparison is `docs → model_docs → rows` versus
`docs → rows`. The duplicate-row comparison is full ORM row → domain model →
full persistence dict versus a dict containing only the nine fingerprint
fields. The metrics log is observability-only and is not expected to improve
throughput.

These 1M quick-win measurements are CPU/memory microbenchmarks separate from
the PostgreSQL wall-clock evidence below. The row-preparation fixture reuses a
lightweight row object to isolate list and mapping overhead; the duplicate-row
test repeats one ORM row to isolate per-row materialization cost. Further clean
path profiling and database-side fingerprint/index work remain candidates for
the performance-acceptance workstream; the temporary conflict-key table is now
the implemented conflict lookup strategy.

Repository acceptance tests separately prove zero clean lookup/hash calls, one
bulk conflict lookup, no N+1 path, concurrent same-key correctness on real
PostgreSQL, and deterministic intra-batch row ordinals. The 100-row integration
fixture proves `95 persisted + 3 rejected + 2 duplicates = 100`, with one
equivalent duplicate, one conflict, `REVIEW`, and `HOLD_FOR_REVIEW`. Airflow
payload tests prove output size is unchanged between one and 10,000 detailed
errors and contains neither raw rows nor fingerprints.

### PostgreSQL conflict-lookup evidence — 2026-08-20

The composite `IN` lookup was replaced by a transaction-scoped temporary key
table with a composite primary key. Keys are loaded with PostgreSQL `COPY`, and
existing payloads are fetched with one set-based `JOIN`. The table is
`ON COMMIT DROP`; no schema migration or permanent index is required. This
removes the PostgreSQL expression-stack failure observed with duplicate-heavy
batches while preserving the existing atomic insert and fingerprint contract.

The wall-clock runs used the real PostgreSQL adapter, `batch_size=20,000`, one
writer, and the existing benchmark cleanup. Results are:

| Scenario | Rows | Result | Elapsed | Throughput |
|---|---:|---|---:|---:|
| Clean | 10,000 | completed | 1.103s | 9,068 rows/s |
| Clean | 100,000 | completed | 10.250s | 9,756 rows/s |
| Clean | 1,000,000 | completed | 111.666s | 8,955 rows/s |
| Equivalent duplicate | 100,000 | 50,000 persisted + 50,000 equivalent | 12.555s | 7,965 rows/s |
| Equivalent duplicate | 1,000,000 | 500,000 persisted + 500,000 equivalent | 144.006s | 6,944 rows/s |
| Conflicting duplicate | 100,000 | 50,000 persisted + 50,000 quarantined | 17.294s | 5,782 rows/s |
| Conflicting duplicate | 1,000,000 | 500,000 persisted + 500,000 quarantined | 193.465s | 5,169 rows/s |

Before this change, the 100,000-row duplicate run with the standard 20,000-row
batch failed with PostgreSQL `stack depth limit exceeded` after processing
60,000 rows. The regression test
`test_large_equivalent_duplicate_batch_uses_scalable_conflict_lookup` pins
that failure mode and verifies 10,000 conflict keys through the new lookup.
The 1M conflict run is intentionally a worst-case quarantine workload; its
throughput includes persistence of 500,000 quarantine records.

The clean path remains lookup-free. After the hot-path optimization described
below, its measured 1M wall-clock throughput is 9.01% below the stored
pre-Workstream-B baseline (8,955 vs 9,762 rows/s), which is within the roughly
10% acceptance target. The duplicate lookup scale issue and the clean-path
regression gate are therefore both closed for this benchmark environment;
repeated environment measurements remain a Workstream F concern.

### Clean-path regression investigation — 2026-08-20

The regression was reproduced against the exact frozen dataset and the same
configuration (`batch_size=20,000`, one writer, `fast_mode=false`). A fresh
baseline run from `HEAD` was compared with Workstream B before and after the
fix. Stage timings are cumulative row metrics; `db_insert_ms` spans the
persisting window and is not additive with the per-row CPU columns.

| Metric, 1M rows | Baseline `HEAD` | B before fix | B after fix |
|---|---:|---:|---:|
| Total ingestion | 102.401s | 116.217s | 111.666s |
| Parse | 9.004s | 9.449s | 8.993s |
| Normalize/build | 15.673s | 16.594s | 19.851s |
| Validate | 1.172s | 6.775s | 2.890s |
| Persisting window | 101.001s | 114.730s | 110.147s |

The dominant confirmed regression was per-row construction of a Pydantic
`QualityEvaluation` even when validation produced no violations. That object
also carried a row-context dictionary that is already represented by the
pipeline `RowOutcome`. The row pipeline now requests a context-free valid
evaluation; the validator returns a shared context-free valid evaluation that
the row pipeline does not mutate, while direct callers retain contextual
evaluations by default. This reduced the 1M validation cost from 6.775s to
2.890s and moved total regression from 13.45% to 9.01%.

The remaining cost is in the broader Workstream B row outcome/accounting and
atomic persistence path, not duplicate lookup on clean data. It is inside the
acceptance budget in this run; further database-side optimization should be
profiled separately so duplicate classification guarantees are not weakened.

## Handoffs

Workstream C owns complete timezone-aware timestamp parsing and the remaining
normalization contract. Workstream D owns quarantine lifecycle/reprocessing
and operator evidence. Workstream F owns production dashboards, alerts,
repeated environment benchmark evidence, and final partner acceptance.
