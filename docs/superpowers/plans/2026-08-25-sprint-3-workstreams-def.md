# Sprint 3 — Workstreams D/E/F Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Workstream B/C quality outputs into one operable quarantine,
review, and production-acceptance flow without changing deterministic quality
semantics, the bounded source-unit result, or the transaction persistence
contract.

**Architecture:** Execute one sequential stream with three review checkpoints:
Workstream D owns the quarantine state machine and source-backed reprocessing;
Workstream E owns actor-scoped decisions and audit evidence; Workstream F
derives bounded metrics and acceptance evidence from those durable events. D → E
→ F is the critical path. This is one reviewable branch and one plan, but not
one atomic change: each workstream ends with a focused test gate and commit.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, MongoDB quarantine/runtime
repositories, PostgreSQL transaction persistence, pytest, Ruff, Mypy, existing
audit and runtime-run services.

**Spec:**
`docs/phase-2/sprint-3-data-quality.md`,
`docs/phase-2/sprint-3-index.md`,
`docs/phase-2/sprint-3-workstream-b-quality-contract.md`, and
`docs/phase-2/sprint-3-workstream-c-normalization-validation.md`.

## Global Constraints

- Preserve the Workstream B decision precedence:
  `BATCH_FATAL > CONFLICTING_DUPLICATE > REJECT > WARNING >
  EQUIVALENT_DUPLICATE > VALID`.
- Preserve the B orchestration outcomes: ordinary rejects remain
  `REVIEW + CONTINUE`, conflicting duplicates remain `HOLD_FOR_REVIEW`, and
  structural failures remain `FAIL`.
- Workstreams D/E/F operate already-routed rejects and duplicates. They do not
  promote amount IQR, fraud semantics, entity consistency, coordinates,
  temporal volume, or timestamp precision drift into automatic rejection.
- Do not add raw rows, complete error payloads, credentials, fingerprints, or
  parsed timestamps to the bounded Airflow/source-unit result or XCom. Any
  operator payload must use sanitized, bounded evidence.
- Do not change transaction-table columns, indexes, Alembic migrations,
  duplicate fingerprint fields, `(identify, ingestion_key)` uniqueness,
  quarantine routing semantics, reconciliation behavior, or mapping-review
  packet semantics.
- Do not overload `ReviewPacket` for row-level quarantine. Reuse the existing
  actor requirement and append-only audit service, but define a distinct
  quarantine action contract.
- The sanitized `rawRow` is evidence for review only; it is never authoritative
  input for canonical reprocessing. Reprocessing must resolve the original
  source file/staged source by `sourceFileId` and `rowNumber`, and must return a
  bounded `SOURCE_EVIDENCE_UNAVAILABLE` failure when the source is gone.
- All state transitions are idempotent and compare-and-set protected. A stale
  operator request must not overwrite a newer claim, resolution, or retry.
- Retention applies to quarantine evidence only. The recommended default is a
  configurable 30-day TTL on `expiresAt`; changing the duration or legal hold
  behavior is an explicit owner decision before implementation.
- Alert thresholds are configuration, not quality rules. Failing an alert must
  never reject a row, alter duplicate classification, or change orchestration.

## Sprint 4 boundary

The repository already has a separate Sprint 4 observability plan. Sprint 3 F
is the data-quality acceptance slice that defines what must be measured and
signed off; Sprint 4 owns the generic runtime-observability implementation.
Therefore this stream does **not** add a new stage model, stage-level metrics
store, structured-log schema, runtime-run schema, dashboard UI, notification
delivery engine, or 100k-record observability benchmark. Those remain in
`docs/phase-2/sprint-4-observability.md`.

The same boundary applies to adjacent workflows: D handles row-level
quarantine records and duplicate conflicts, not Sprint 2.5 source-unit retry,
Airflow backfill, or checkpoint recovery; E handles row-level quarantine
decisions, not mapping `ReviewPacket` approval or runtime `WAITING_REVIEW`.

## Pre-flight decision gate

Before changing code, record the owner decisions below in the sprint issue or
review note. The recommended choices make the rest of this plan executable.

- Retention: Mongo quarantine records receive `expiresAt`; default retention is
  30 days, with a configurable override and a future legal-hold extension
  point. Expiration removes only the sanitized evidence document; audit events
  retain bounded action metadata.
- Reprocessing source: resolve the persisted source-file/staged-source path by
  `sourceFileId`; verify the row number and file identity before reading. Do not
  reconstruct a row from sanitized `rawRow`.
- Operator authorization: retain the current `X-Actor`/payload actor contract.
  D/E add required `reason` for destructive actions, not a new RBAC system.
- Quarantine actions: `CLAIM`, `REPROCESS`, `RESOLVE`, and `REJECT`. A claim is
  exclusive; reprocess is the only action allowed to create a new ingestion
  attempt; resolve/reject require an actor and reason.
- F acceptance thresholds: use config-backed thresholds for pending age,
  reject rate, conflicting-duplicate rate, reprocess success rate, unavailable
  source evidence, and terminal runtime latency. The owner must supply numeric
  values and notification sink before production sign-off.

## Task 1 — Freeze the D/E/F contracts and blast radius

**Files:**

- Modify: `docs/phase-2/sprint-3-data-quality.md`
- Modify: `docs/phase-2/sprint-3-index.md`
- Create: `docs/phase-2/sprint-3-workstreams-def-contract.md`
- Tests: `tests/test_ingestion_components.py`,
  `tests/test_api_operations.py`

**Interfaces:**

- Define the quarantine transition table and bounded action response before
  implementation.
- Define the operator action payload as `{actor, reason?, expectedStatus}` and
  response as `{recordId, status, attemptCount, sourceEvidenceAvailable,
  actionId}`; never include unsanitized source data.
- Define F metric names, dimensions, threshold configuration, and alert event
  shape without adding fields to `SourceUnitResult`.

**Steps:**

- [ ] Write the contract document with the transition table:
  `PENDING → REPROCESSING → RESOLVED|REJECTED`, `PENDING → RESOLVED|REJECTED`
  for manual disposition, and `PENDING|REPROCESSING →` retention expiry only
  through the retention worker/index.
- [ ] Document that duplicate conflicts and ordinary rejects retain their
  existing `QuarantinePhase`, `QuarantineSeverity`, rule codes, and source-unit
  orchestration outcome.
- [ ] Add generated-fixture contract tests for bounded response fields and
  absence of `rawRow`, credentials, fingerprints, and parsed timestamps.
- [ ] Run `uv run pytest tests/test_ingestion_components.py
  tests/test_api_operations.py -q` and review the contract before coding D.

## Task 2 — Implement Workstream D quarantine lifecycle storage

**Files:**

- Modify: `src/domain/ingestion/quarantine.py`
- Modify: `src/infrastructure/ingestion/quarantine_repository.py`
- Modify: `src/infrastructure/persistence/mongo_indexes.py`
- Create: `tests/test_quarantine_lifecycle.py`
- Modify: `tests/test_ingestion_components.py`

**Interfaces:**

- Extend the quarantine model with bounded lifecycle metadata: `expiresAt`,
  `claimedBy`, `claimedAt`, `lastActionId`, and `lastErrorCode` where needed.
- Add repository operations `get`, `list` with partner/status/age filters,
  `claim_pending`, `transition`, and `count_by_status`.
- Every mutation must filter by record id, current status, and optional
  `expectedStatus`; return a typed conflict/not-found result rather than
  silently updating zero documents.

**Steps:**

- [ ] Preserve `sanitize_raw_row` and all existing field aliases; add only
  bounded lifecycle metadata.
- [ ] Implement compare-and-set transitions and monotonic `attemptCount`.
- [ ] Add the `expiresAt` index/TTL behavior in Mongo only; do not add a
  PostgreSQL migration or transaction-table schema change.
- [ ] Prove pending ordering, duplicate claim rejection, idempotent replay,
  status-filtered listing, and TTL metadata with deterministic fixtures.
- [ ] Run `uv run pytest tests/test_quarantine_lifecycle.py
  tests/test_ingestion_components.py -q` and `uv run ruff check
  src/domain/ingestion/quarantine.py
  src/infrastructure/ingestion/quarantine_repository.py
  src/infrastructure/persistence/mongo_indexes.py`.

## Task 3 — Implement source-backed D reprocessing

**Files:**

- Create: `src/application/ingestion/quarantine_service.py`
- Modify: `src/application/ingestion/source_unit_orchestrator.py`
- Modify: `src/application/automation/stream_ingestion.py`
- Modify: `src/pipeline/row_pipeline.py`
- Create: `tests/test_quarantine_reprocessing.py`
- Modify: `tests/test_source_unit_orchestrator.py`

**Interfaces:**

- `QuarantineService.claim(record_id, actor, action_id)` claims one pending
  record through the repository CAS operation.
- `QuarantineService.reprocess(record_id, actor, reason, action_id)` resolves
  source evidence, reruns the existing row pipeline with the current approved
  mapping/config, and transitions the record based on the normal B/C result.
- A missing or mismatched source must return bounded
  `SOURCE_EVIDENCE_UNAVAILABLE`; it must not expose a path, raw row, or
  exception string.

**Steps:**

- [ ] Reuse existing source-file identity/path resolution and row-reader
  boundary; do not create a second normalizer, validator, or duplicate lookup.
- [ ] Persist a bounded attempt summary (`actionId`, actor, outcome, rule
  codes, timestamps, runtime/run id) and never persist a complete rejected row.
- [ ] Map successful reprocessing to `RESOLVED` only after normal persistence
  succeeds; map a still-invalid row to `REJECTED` with the existing rule code;
  leave infrastructure failures retryable in `REPROCESSING` with a bounded
  error code.
- [ ] Add tests for successful reprocess, still-invalid reprocess, duplicate
  claim, missing source, retry after transient failure, and no raw-value leak.
- [ ] Run `uv run pytest tests/test_quarantine_reprocessing.py
  tests/test_source_unit_orchestrator.py -q`.

## Task 4 — Expose the D operator lifecycle API

**Files:**

- Create: `src/api/quarantine.py`
- Modify: `src/api/operations.py`
- Modify: `src/api/actor.py` only if bounded validation helpers are required
- Create: `tests/test_api_quarantine.py`
- Modify: `tests/test_api_operations.py`

**Interfaces:**

- `GET /api/v1/operations/quarantine` supports bounded partner/status/age
  filters and pagination.
- `GET /api/v1/operations/quarantine/{record_id}` returns sanitized evidence
  and lifecycle metadata.
- `POST /api/v1/operations/quarantine/{record_id}/claim` requires actor and
  action id.
- `POST /api/v1/operations/quarantine/{record_id}/reprocess` requires actor,
  reason, action id, and expected status.
- `POST /api/v1/operations/quarantine/{record_id}/resolve` and `/reject`
  require actor, reason, action id, and expected status.

**Steps:**

- [ ] Keep existing pending-quarantine summaries backward compatible.
- [ ] Return stable conflict/not-found/validation codes and avoid leaking
  repository exception text.
- [ ] Add API tests for actor enforcement, reason enforcement, CAS conflicts,
  pagination bounds, redaction, and idempotent action replay.
- [ ] Run `uv run pytest tests/test_api_quarantine.py
  tests/test_api_operations.py -q`.
- [ ] Review checkpoint: commit D only after the D tests, Ruff, and diff guard
  pass.

## Task 5 — Implement Workstream E ownership, decisions, and audit

**Files:**

- Modify: `src/application/audit/service.py`
- Modify: `src/domain/audit/models.py` if a bounded quarantine action event
  type is needed
- Modify: `src/application/ingestion/quarantine_service.py`
- Modify: `src/api/quarantine.py`
- Create: `tests/test_quarantine_review_actions.py`
- Modify: `tests/test_audit.py` or the repository’s existing audit tests

**Interfaces:**

- Emit append-only audit events for `CLAIM`, `REPROCESS_REQUESTED`,
  `REPROCESS_SUCCEEDED`, `REPROCESS_FAILED`, `RESOLVED`, `REJECTED`, and
  `ESCALATED` with actor, action id, record id, old/new status, bounded reason,
  and outcome code.
- Add a deterministic ownership view derived from quarantine status and audit
  events; do not introduce a second review-packet lifecycle.
- Repeated action ids return the original bounded result and do not duplicate
  the state transition or audit event.

**Steps:**

- [ ] Require actor for every mutation and a non-empty bounded reason for
  resolve/reject/escalate.
- [ ] Enforce that only the claimant or an explicitly configured escalation
  actor can finish a `REPROCESSING` record.
- [ ] Define escalation as an audit-visible action plus status-preserving
  ownership transfer; it must not change quality outcome.
- [ ] Add tests for ownership conflicts, replay/idempotency, actor/reason
  validation, audit metadata bounds, and unchanged B/C rule codes.
- [ ] Run `uv run pytest tests/test_quarantine_review_actions.py
  tests/test_audit.py -q`.
- [ ] Review checkpoint: commit E only after the audit and API contract is
  approved.

## Task 6 — Define the Workstream F data-quality acceptance baseline

**Files:**

- Modify: `docs/phase-2/sprint-3-workstreams-def-contract.md`
- Create: `docs/phase-2/sprint-3-workstreams-def-evidence.md`
- Modify: `tests/test_quality_contract.py`
- Modify: `tests/test_api_operations.py`
- Modify: `tests/test_source_unit_orchestrator.py`

**Interfaces:**

- Define the F acceptance metrics from data already emitted by
  `IngestionResult.bounded_source_unit_result()`, `RunState.quality_counters`,
  existing file summaries, and the D/E quarantine audit events:
  `input_rows`, `rejected_rows`, `conflicting_duplicate_rows`,
  `pending_quarantine`, `reprocess_success_rate`, and
  `source_evidence_unavailable`.
- Keep the existing read-only operations endpoint as the source of operational
  visibility. Do not add a generic observability endpoint in Sprint 3.
- Define threshold and sign-off records as documentation/configuration inputs
  for Sprint 4. They must not create alert events or mutate quality outcomes in
  this stream.

**Steps:**

- [ ] Add generated-fixture assertions that the existing counters reconcile with
  input/persisted/rejected/quarantined rows and remain bounded.
- [ ] Add generated-fixture assertions that ordinary rejects and conflicting
  duplicates remain distinct, and that no F metric contains raw rows, parsed
  timestamps, credentials, fingerprints, or full exception text.
- [ ] Record the proposed threshold names, owner, window, and sign-off evidence
  required by Sprint 4 without implementing a notification sink.
- [ ] Run `uv run pytest tests/test_quality_contract.py
  tests/test_api_operations.py tests/test_source_unit_orchestrator.py -q`.

## Task 7 — Close Sprint 3 F and hand off platform observability to Sprint 4

**Files:**

- Modify: `docs/phase-2/sprint-3-workstreams-def-evidence.md`
- Modify: `docs/phase-2/sprint-3-data-quality.md`
- Modify: `docs/phase-2/sprint-3-index.md`
- Modify: `docs/phase-2/INDEX.md`
- Modify: `docs/INDEX.md`

**Interfaces:**

- The evidence document must state the D lifecycle contract, E operator/audit
  contract, F metric definitions, proposed thresholds, partner sign-off
  criteria, rollback/disable expectations, and the explicit Sprint 4 handoff.
- Sprint 3 must not claim a dashboard, alert delivery, stage-level runtime
  metrics, or production observability implementation that belongs to Sprint 4.

**Steps:**

- [ ] Write the evidence document with these sections: Scope and non-goals;
  D lifecycle contract; E operator and audit contract; F data-quality metric
  definitions; proposed threshold/sign-off matrix; generated fixture evidence;
  production acceptance boundary; and Sprint 4 observability handoff.
- [ ] Keep the C status text accurate: the full-dataset v2 artifact remains
  pending until it is actually generated; do not claim a live benchmark here.
- [ ] Run `uv run pytest tests/test_quality_contract.py
  tests/test_api_operations.py tests/test_source_unit_orchestrator.py -q`.
- [ ] Review checkpoint: commit F only after owners approve the acceptance
  matrix and explicitly accept the Sprint 4 handoff.

## Task 8 — End-to-end verification and closeout

**Files:**

- No production code changes unless a verification failure identifies a scoped
  contract defect.
- Modify the D/E/F evidence/index documents only to record measured results.

**Steps:**

- [ ] Run the focused D/E/F suite:
  `uv run pytest tests/test_quarantine_lifecycle.py
  tests/test_quarantine_reprocessing.py tests/test_api_quarantine.py
  tests/test_quarantine_review_actions.py tests/test_quality_contract.py
  tests/test_api_operations.py tests/test_source_unit_orchestrator.py -v
  --tb=short`.
- [ ] Run the existing backend suite with the repository’s environment-gated
  exclusions, then PostgreSQL-backed integration/migration tests separately.
- [ ] Run `uv run ruff check src dags scripts cli tests` and
  `uv run mypy src/ --show-error-codes`.
- [ ] Run `git diff --check` and inspect `git diff --stat` plus the CodeGraph
  impact for quarantine API, runtime validation, audit, and source-unit
  serialization paths.
- [ ] Verify bounded-result snapshots contain no raw rows, parsed timestamps,
  credentials, fingerprints, or full exception text.
- [ ] Verify B/C focused suites and the stored Workstream B clean-path
  performance acceptance remain unchanged.
- [ ] Update status to `implemented` only when D/E/F gates and owner sign-off
  pass; otherwise use an exact pending-evidence status.
- [ ] Create one final closeout commit after all evidence is reproducible.

## Critical path and review checkpoints

```text
Contract/decision gate
        ↓
D1 lifecycle storage → D2 source-backed reprocess → D3 lifecycle API
        ↓ review checkpoint
E1 ownership + audit → E2 operator decision tests
        ↓ review checkpoint
F1 quality acceptance baseline → F2 evidence + Sprint 4 handoff
        ↓
full verification and closeout
```

This can be executed as one branch and one review sequence. It should remain
sequential at the task level because E depends on D’s transition/action IDs and
F depends on D/E’s durable counters and audit events. The only blocking inputs
before implementation are the retention/legal-hold choice and the numeric F
thresholds/notification owner; the recommended defaults above keep the stream
otherwise self-contained.
