# Sprint 3 — Workstreams D/E/F Minimal Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the smallest safe operational contract around the Workstream
B/C quarantine outputs: lifecycle, operator action/audit, and data-quality
acceptance evidence. Keep the implementation on the existing Mongo quarantine,
operations API, audit service, runtime counters, and tests.

**Architecture:** One sequential branch with four checkpoints:

`D persistence/state` → `D/E actions + audit` → `F acceptance evidence` →
verification/closeout.

This is intentionally not a new recovery or observability platform. D operates
row-level quarantine records; E records row-level operator decisions; F defines
the quality acceptance evidence consumed by the existing operations view and
the future Sprint 4 observability work.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, MongoDB/Motor, existing
append-only audit service, pytest, Ruff, Mypy.

**Spec:**
`docs/phase-2/sprint-3-data-quality.md`,
`docs/phase-2/sprint-3-index.md`,
`docs/phase-2/sprint-3-workstream-b-quality-contract.md`,
`docs/phase-2/sprint-3-workstream-c-normalization-validation.md`, and
`docs/phase-2/sprint-4-observability.md` for the explicit handoff boundary.

## Blast-radius guardrails

- Do not modify `src/pipeline/run_state.py`,
  `src/application/ingestion/source_unit_orchestrator.py`,
  `src/application/automation/stream_ingestion.py`, runtime models, Airflow
  APIs, structured logging, reconciliation, or `ReviewPacket` semantics.
- Do not add a PostgreSQL/Alembic change, transaction-table field, duplicate
  lookup, new quality rule, new orchestration outcome, or new XCom field.
- Do not add a generic observability module/API, stage metrics store, dashboard
  UI, notification sink, or 100k-record observability benchmark. Those belong
  to Sprint 4.
- Preserve the B/C precedence and outcomes exactly:
  `BATCH_FATAL > CONFLICTING_DUPLICATE > REJECT > WARNING >
  EQUIVALENT_DUPLICATE > VALID`; ordinary rejects remain `REVIEW + CONTINUE`,
  conflicts remain `HOLD_FOR_REVIEW`, and structural failure remains `FAIL`.
- Never expose unsanitized rows, complete errors, credentials, fingerprints, or
  parsed timestamps through an operator response, audit metadata, or the
  bounded source-unit result.
- Preserve the existing `X-Actor`/payload actor requirement. Add no RBAC
  system in this workstream.

## Required decision gate before coding

The following bounded choices are part of the plan and must be recorded in the
review decision:

1. **Retention:** add `expiresAt` to quarantine records with a configurable
   30-day default and a Mongo TTL index. TTL removes only sanitized quarantine
   evidence; append-only audit records remain. No legal-hold implementation is
   added here.
2. **Source authority:** `rawRow` is review evidence only. It cannot be used to
   reconstruct a canonical transaction because it may be masked or truncated.
3. **Reprocess semantics for the low-blast-radius stream:** a reprocess action
   is an auditable request/claim for an existing source-unit replay only when
   `sourceUnitKey` is present. The action returns
   `SOURCE_EVIDENCE_UNAVAILABLE` when no retained source identity exists and
   never invents a row-level replay engine. Completion is recorded by the
   existing operator/runtime flow through a subsequent resolve/reject action.
   One-click source-unit execution requires a separate Sprint 2.5 integration
   decision and is explicitly outside this plan.
4. **F thresholds:** record metric names, owners, windows, and proposed numeric
   thresholds as acceptance inputs for Sprint 4. Do not implement alert delivery
   in Sprint 3.

## Task 1 — D: Extend quarantine lifecycle metadata and CAS persistence

**Files:**

- Modify: `src/domain/ingestion/quarantine.py`
- Modify: `src/config/settings.py`
- Modify: `src/infrastructure/ingestion/quarantine_repository.py`
- Modify: `src/infrastructure/persistence/mongo_indexes.py`
- Create: `tests/test_quarantine_lifecycle.py`
- Modify: `tests/test_ingestion_components.py`

**Interfaces:**

- Add bounded metadata fields to `IngestionQuarantineRecord`:
  `expiresAt`, `claimedBy`, `claimedAt`, and `lastActionId`. Keep current
  statuses (`PENDING`, `REPROCESSING`, `RESOLVED`, `REJECTED`) and all existing
  error/phase/severity fields.
- Add repository methods:
  `find_by_id(record_id)`, `list_records(partner, status, limit)`, and
  `transition(record_id, expected_status, new_status, metadata, action_id)`.
- `transition` must use a Mongo filter containing record id and expected status;
  a stale request returns a typed conflict/not-found result. Existing
  `mark_status` remains available for compatibility but is not used by new
  mutating endpoints.

**Steps:**

- [ ] Default `expiresAt` from one configuration value without changing the
  existing quarantine creation call sites’ required arguments.
- [ ] Make action metadata bounded and omit raw row, complete exception text,
  fingerprints, and credentials.
- [ ] Add a TTL index on `expiresAt` for the existing
  `ingestion_quarantine_record` collection; do not add a migration.
- [ ] Test pending ordering, partner/status filters, CAS conflicts,
  idempotent action-id replay, expiration metadata, and preservation of
  `sanitize_raw_row` behavior.
- [ ] Run:
  `uv run pytest tests/test_quarantine_lifecycle.py
  tests/test_ingestion_components.py -q`
  and
  `uv run ruff check src/domain/ingestion/quarantine.py
  src/infrastructure/ingestion/quarantine_repository.py
  src/infrastructure/persistence/mongo_indexes.py`.
- [ ] Review checkpoint: commit D persistence only after the focused tests and
  diff guard pass.

## Task 2 — D/E: Add one quarantine action service and bounded operations routes

**Files:**

- Create: `src/application/ingestion/quarantine_actions.py`
- Modify: `src/api/operations.py`
- Reuse: `src/api/actor.py`
- Reuse: `src/application/audit/service.py`
- Create: `tests/test_quarantine_actions.py`
- Modify: `tests/test_api_operations.py`
- Modify: `tests/test_api_audit.py` only if the existing audit query needs a
  quarantine entity filter

**Interfaces:**

- `GET /api/v1/operations/quarantine` — bounded list/detail projection with
  partner/status/limit filters; return sanitized evidence only.
- `POST /api/v1/operations/quarantine/{record_id}/claim` — actor and
  `actionId`; transition `PENDING → REPROCESSING`, recording ownership.
- `POST /api/v1/operations/quarantine/{record_id}/reprocess` — actor,
  `actionId`, and expected status; emit a source-backed replay request when
  `sourceUnitKey` exists, otherwise return bounded
  `SOURCE_EVIDENCE_UNAVAILABLE` without changing state.
- `POST /api/v1/operations/quarantine/{record_id}/resolve` and `/reject` —
  actor, non-empty bounded reason, `actionId`, and expected status; transition
  to the final state.
- Every mutation writes an audit event with entity type `INGESTION_QUARANTINE`,
  record id, actor, action, old/new status, action id, bounded reason/outcome.

**State/action contract:**

| Action | Allowed state | New state | Notes |
|---|---|---|---|
| `CLAIM` | `PENDING` | `REPROCESSING` | Exclusive CAS ownership claim |
| `REPROCESS` | `REPROCESSING` | `REPROCESSING` | Request only; source identity required |
| `RESOLVE` | `PENDING`/`REPROCESSING` | `RESOLVED` | Actor and reason required |
| `REJECT` | `PENDING`/`REPROCESSING` | `REJECTED` | Actor and reason required |

**Steps:**

- [ ] Keep the service independent of normalizer, validator, row pipeline,
  Airflow, and reconciliation code. It must not parse or rebuild rows.
- [ ] Make repeated `actionId` requests return the original bounded result
  without a second transition or audit event.
- [ ] Make stale expected-status requests return a stable conflict response;
  never overwrite a newer operator decision.
- [ ] Enforce actor/reason validation and audit metadata bounds.
- [ ] Add tests for claim ownership, unavailable source, resolve/reject,
  replay/idempotency, stale status, sanitized response, and unchanged B/C rule
  evidence.
- [ ] Run:
  `uv run pytest tests/test_quarantine_actions.py
  tests/test_api_operations.py tests/test_api_audit.py -q`.
- [ ] Review checkpoint: commit E after action/audit tests pass. Do not modify
  mapping review APIs or automation recovery routes.

## Task 3 — F: Freeze data-quality acceptance evidence and Sprint 4 handoff

**Files:**

- Create: `docs/phase-2/sprint-3-workstreams-def-evidence.md`
- Modify: `tests/test_quality_contract.py`
- Modify: `tests/test_api_operations.py`
- Modify: `docs/phase-2/sprint-3-data-quality.md`
- Modify: `docs/phase-2/sprint-3-index.md`
- Modify: `docs/phase-2/INDEX.md`
- Modify: `docs/INDEX.md`

**Interfaces:**

- Use existing `IngestionResult.bounded_source_unit_result()`,
  `RunState.quality_counters`, file summaries, quarantine state, and audit
  events as evidence sources. Do not change their schemas.
- Freeze these data-quality metrics for the handoff:
  `inputRows`, `persistedRows`, `rejectedRows`, `duplicateRows`,
  `quarantinedRows`, `pendingQuarantine`, `reprocessRequested`,
  `sourceEvidenceUnavailable`, and final quality/orchestration decision.
- Define threshold/owner/window fields in the evidence document only. No new
  alert endpoint, dashboard, logger event, or notification delivery code.

**Steps:**

- [ ] Add generated-fixture tests proving counters reconcile and ordinary
  rejects/conflicting duplicates remain distinct.
- [ ] Add bounded-output tests proving no raw row, parsed timestamp,
  credential, fingerprint, or full exception leaks through F evidence.
- [ ] Document partner sign-off, rollback/disable expectations, retention,
  operator ownership, and the explicit Sprint 4 handoff for stage metrics,
  structured logs, dashboards, alerts, and 100k observability benchmark.
- [ ] Keep Workstream C status exactly
  `implemented; full-dataset v2 evidence pending` until its artifact exists.
- [ ] Run:
  `uv run pytest tests/test_quality_contract.py
  tests/test_api_operations.py -q`.
- [ ] Review checkpoint: commit F only after the acceptance matrix is approved.

## Task 4 — Full verification and closeout

**Steps:**

- [ ] Run focused D/E/F tests:
  `uv run pytest tests/test_quarantine_lifecycle.py
  tests/test_quarantine_actions.py tests/test_ingestion_components.py
  tests/test_api_operations.py tests/test_api_audit.py
  tests/test_quality_contract.py -v --tb=short`.
- [ ] Run the existing backend suite with its environment-gated exclusions and
  the PostgreSQL integration/migration suite separately.
- [ ] Run `uv run ruff check src dags scripts cli tests` and
  `uv run mypy src/ --show-error-codes`.
- [ ] Run `git diff --check` and inspect the final diff for forbidden changes
  to Airflow, runtime models, RunState, source-unit orchestration,
  reconciliation, mapping review, duplicate SQL, and transaction schema.
- [ ] Re-run the Workstream B/C focused suites and confirm the stored B clean
  performance acceptance remains unchanged.
- [ ] Update status only from measured evidence; do not claim Sprint 4
  observability is implemented.
- [ ] Create one closeout commit after all gates pass.

## Critical path

```text
Decision gate
    ↓
D1 quarantine fields/CAS/TTL
    ↓ checkpoint
D2/E action service + operations API + audit
    ↓ checkpoint
F acceptance counters/evidence + Sprint 4 handoff
    ↓
full verification and closeout
```

This is feasible as one low-blast-radius implementation stream. The only
intentional boundary is source-unit execution: this plan records and audits a
reprocess request when source identity exists, but does not create a second
row/source replay engine. If one-click reprocessing is required, it should be
approved as a separate integration change against the existing Sprint 2.5
recovery flow rather than added here.
