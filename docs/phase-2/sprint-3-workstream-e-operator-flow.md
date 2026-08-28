# Workstream E — Operator quarantine workflow

**Status:** Implemented at the domain, application, persistence, API, and
contract-test level. Production acceptance and partner sign-off remain outside
this evidence document.

Workstream E completes the row-level operator workflow for quarantine records
in `REVIEW`. It extends the existing D quarantine document and resolution
service. `resolutionHistory` is the bounded action ledger in that document;
the existing audit service remains the append-only audit projection. No queue
collection, parallel action service, normalizer, or frontend workflow was
added.

Row-level approval does not approve a mapping or a `ReviewPacket`. Mapping
approval continues to use the existing `ReviewPacket` and mapping approval
contracts.

## State and action contract

| Action | Allowed state | Result | Ownership rule |
|---|---|---|---|
| `CLAIM` | `PENDING` | `REPROCESSING` | Atomic lease-bound claim; one winner |
| `REPROCESS` | `REPROCESSING` | `RESOLVED` or `PENDING` | Current claimant only |
| `ACCEPT_EXISTING` | `REPROCESSING` | `RESOLVED` | Internal fingerprint verification; current claimant only |
| `REJECT` | `REPROCESSING` | `REJECTED` | Non-empty bounded reason; current claimant only |
| `ESCALATE` | `PENDING` or `REPROCESSING` | State unchanged | Current claimant for `REPROCESSING` |

The only lifecycle transitions are `PENDING → REPROCESSING → PENDING`,
`RESOLVED`, or `REJECTED`. There is no public `RESOLVE` bypass. Ordinary B/C
row rejects remain `REVIEW + CONTINUE`; conflicting duplicates remain
`HOLD_FOR_REVIEW`; structural failures remain `FAIL`.

Every mutation uses an `actionId` (maximum 128 characters) and an
`expectedStatus`. The idempotency scope is `(recordId, actionId)`. Repeating
the same action with the same actor returns the recorded bounded result and
does not perform another transition or audit write. Reusing that ID for a
different actor or action returns `ACTION_ID_REUSE_CONFLICT`.

The source-unit resume route is the checkpoint-owned recovery exception: it
requires `actionId` and a bounded reason, but has no row `expectedStatus` and
does not append to a quarantine record's `resolutionHistory`. Its existing
checkpoint state machine remains the source of truth.

## API contract

The source-of-truth namespace is `/api/v1/quarantine`:

```text
GET  /api/v1/quarantine
GET  /api/v1/quarantine/{record_id}
POST /api/v1/quarantine/{record_id}/claim
POST /api/v1/quarantine/{record_id}/reprocess
POST /api/v1/quarantine/{record_id}/accept-existing
POST /api/v1/quarantine/{record_id}/reject
POST /api/v1/quarantine/{record_id}/escalate
POST /api/v1/quarantine/source-units/{source_unit_key}/resume
```

After the active rows in a post-approval batch are clear, the parent packet
also exposes `POST /api/v1/review-packets/{packet_id}/post-approve-run/continue`
for an explicit operator Proceed action. It is CAS-bound and idempotent: a
completed run returns `ALREADY_RECONCILED` without running reconciliation again.

Mutation payloads carry `actionId` and `expectedStatus`. The actor is
`operatorId` or the existing `X-Actor` header. `REJECT` and `ESCALATE` require
a non-empty reason of at most 500 characters. `CORRECTED_ROW` requires
`correctedRow`; `ACCEPT_EXISTING` verifies the existing fingerprint inside the
resolution service and never returns it.

Action responses contain only bounded lifecycle data: record/action IDs,
outcome, old/new status, attempt count, owner, priority, review due time,
escalation level, source-evidence availability, quality counters, and stable
`errorCodes`. Queue responses contain bounded items, a cursor, and a summary
of `pending`, `reprocessing`, `resolved`, `rejected`, `overdue`, and
`highPriority` counts. Summary counts are computed independently of page size
and cursor.

HTTP error mapping is stable: `400` for actor or payload contract errors,
`404` for a missing record, `409` for stale/CAS/ownership/fingerprint/action
conflicts, `422` for missing reason/corrected row/source evidence or
validation outcomes, and `503` for bounded retryable dependency outcomes.

## Scheduler-to-quarantine packet flow

The operator path keeps the existing Review Packet as the parent of a
post-approval quarantine batch:

```text
scheduler run → pending Review Packet → mapping quality gate → approve packet
  → post-approval ingestion → quality gate
      ├─ PASS → reconciliation continues
      └─ REVIEW_REQUIRED → grouped quarantine packet
           → resolve all active rows → parent packet shows Proceed
           → operator selects Proceed → reconciliation continues
```

Each post-approval quarantine row carries the packet/run correlation. The
queue groups rows by that correlation. Resolving the final active row leaves
the post-approval run waiting; the parent packet exposes the existing
compare-and-set continuation explicitly for the operator. The continuation is
manual, idempotent, and does not create a second queue or bypass mapping
approval. The local mock demo uses the
existing scheduler endpoint with the `local` orchestrator when Airflow is not
running; this is an execution adapter choice, not a new workflow contract.

## Priority, SLA, and escalation

The default review SLA is 24 hours and is configurable through
`APP_INGESTION_QUARANTINE_REVIEW_SLA_HOURS`. `reviewDueAt` is derived from
`createdAt + SLA`. A record is overdue only while it is `PENDING` or
`REPROCESSING` and `now >= reviewDueAt`.

`CONFLICTING_DUPLICATE` and `FATAL` records have `HIGH` priority; all other
records are `NORMAL`. Escalation increments `escalationLevel` up to a cap of
3, records the operator and timestamp, preserves status and owner, and does
not change priority by itself.

Claims carry a lease. A live lease is required for reprocess, accept-existing,
reject, and reprocessing-state escalation; an expired claim cannot be mutated
by its previous owner. The next claim atomically returns an expired claim to
`PENDING` before acquiring a fresh lease.

Escalation does not send notifications, transfer ownership, or enforce RBAC in
Sprint 3. Those are Sprint 4 or later handoffs.

## Audit and redaction policy

Successful mutations write one `INGESTION_QUARANTINE` audit event with actor,
action ID, previous/new status, outcome, bounded reason, partner, and source
unit metadata. A unique action-scoped audit index (partial/sparse by string
`actionId`) on
`(entityType, entityId, metadata.actionId)` makes audit projection retries
idempotent.

Successful source-unit resume writes the same bounded audit projection under
`INGESTION_QUARANTINE_SOURCE_UNIT`; it records `HELD → RESUMED` and remains
outside the row-level action ledger.

Public records and audit metadata do not expose raw rows, credentials, full
exceptions, parsed timestamps, or incoming/existing transaction fingerprints.
Detail views may include sanitized evidence and a bounded resolution history;
raw-row secret fields are masked and resolution metadata is recursively
bounded/redacted. Persistence and audit metadata also drop sensitive evidence
keys.

## Acceptance evidence

| Contract | Evidence |
|---|---|
| Concurrent claim has one winner | Repository atomic `find_one_and_update` with `PENDING` CAS and lease tests |
| Stale status/wrong owner cannot mutate | Service ownership tests and repository status/claim filters |
| Source replay and shared row processing | Reprocess service tests; source authority is selected by the existing D reader |
| Accept existing | Internal fingerprint-reader verification tests; fingerprint is absent from API/audit output |
| Reject | Required reason and terminal `REJECTED` tests |
| Escalation | Status-preserving increment, owner CAS, cap 3, bounded metadata tests |
| Idempotent replay | Resolution-history lookup tests; persistence is not called again |
| Audit | Action lookup, sparse unique index, and bounded audit metadata tests |
| Queue | Filter, cursor, page-independent summary, priority, and overdue tests |

The focused E/D contract gate is run with the commands in the CI map and the
Sprint 3 index. These tests are unit/contract evidence only; they do not
constitute production sign-off or partner acceptance.

## Sprint 4 handoff

Workstream F owns live environment evidence, partner sign-off, and production
acceptance. Sprint 4 owns notification delivery, an operator dashboard,
stage-level metrics, alerting, and broader observability implementation.
