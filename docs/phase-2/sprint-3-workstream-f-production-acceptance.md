# Workstream F — Data-quality demo acceptance and handoff

**Status:** `GO (demo-only)`. The local Compose topology and mock-data
acceptance gates pass. Production acceptance, partner sign-off, and cutover
are outside this demo scope.

**Scope:** Workstream F is a demo acceptance and handoff gate. It validates the
existing B/C/D/E contracts through the current CI and local Compose topology.
It does not add runtime behavior or claim production readiness.

## Ownership boundary

Workstream F owns:

- demo evidence for deterministic quality, normalization, quarantine lifecycle,
  source-unit recovery, and operator actions;
- demo owner review of the data-quality and quarantine outcomes;
- the sanitized handoff package for Sprint 4.

Sprint 4 owns notification delivery, dashboards, alerting, structured logs,
stage-level metrics, and the observability benchmark. F may record existing
counters and outcomes as acceptance evidence, but it does not implement or
benchmark a new observability layer.

Mapping approval remains on the existing `ReviewPacket` contract. Row-level
quarantine approval does not approve a mapping, change reconciliation scope,
or replace the existing review workflow. Sprint 2.5 acceptance gaps are
dependencies for the environment gate, not implementation work in F.

## Required inputs

| Input | Source | F requirement |
|---|---|---|
| Deterministic quality outcomes and counters | [Workstream B contract](sprint-3-workstream-b-quality-contract.md) | Preserve `PASS / CONTINUE`, `REVIEW / CONTINUE`, `HOLD_FOR_REVIEW`, and `FAIL` semantics |
| Normalization and validation parity | [Workstream C contract](sprint-3-workstream-c-normalization-validation.md) | Preserve canonical `transDate`, error codes, and normal/fast parity |
| Full-dataset baseline | [Workstream C baseline](sprint-3-workstream-c-baseline.md) | Attach existing 1M-row evidence; do not turn it into an observability benchmark |
| Quarantine lifecycle and recovery | [Sprint 3 data-quality contract](sprint-3-data-quality.md#d--quarantine-lifecycle--implemented) | Verify source authority, checkpoint ordering, hold/resume, and bounded evidence |
| Operator workflow | [Workstream E flow](sprint-3-workstream-e-operator-flow.md) | Verify ownership, CAS, action replay, audit idempotency, SLA, and redaction |
| Runtime topology | [CI map](../CI-MAP.md#full-topology-contract) | Verify API, source, SFTP, MongoDB, PostgreSQL, and Airflow work together |

## Execution record

Recorded at `2026-08-27T15:06:55Z` against commit
`d9b11f4bfcf34cffa6cb37812ebda69f84e079fe` using local mock data.

| Check | Result |
|---|---|
| Full local pytest | `1326 passed, 18 skipped` in `19.26s` |
| Focused B/C/D/E/API gate | `209 passed` in `2.68s` |
| Ruff | Pass: `All checks passed!` |
| Mypy | Pass: no issues in `207 source files` |
| Compose configuration | Pass: `docker compose config --quiet` |
| Full topology contract | Local Compose mock-data pass: `1 passed` in `17.64s` |
| Demo acceptance decision | `GO` |
| Production readiness decision | Not assessed; outside demo scope |

No staging endpoint, production credential, or partner fixture is required for
this demo. The topology fixture uses mock data and must remain local because it
wipes MongoDB and PostgreSQL before seeding its test data.

## Local Review Center quarantine demo

The operator UI is available in the existing Review Center under the
`Quarantine` tab. It consumes the existing `/api/v1/quarantine` namespace; no
second queue or workflow is created. The demo starts at the scheduler and uses
the local orchestrator adapter when Airflow is not running:

```bash
docker compose up -d --build --wait postgres mongodb api
make quarantine-demo-reset
make quarantine-demo-run
cd frontend-next && npm run dev
```

Open Review Center → Review Packets, complete mapping quality-gate review, and
approve the packet. The post-approval quality gate then groups active rows
under the packet/run in the Quarantine tab. Use actor `demo-operator` to
resolve the rows; after the final active row, click `Proceed to reconciliation`
to start the next step manually. The reset does not insert quarantine records or
a fatal packet directly. It writes a FILEDROP source file with 20 rows (18
ordinary rows, one conflicting duplicate, and one row missing the required
`amount`), one existing partner transaction for the conflict, and 20 internal
source-of-truth transactions for reconciliation. It also registers `DEMO1` as
a second FILEDROP schedule with an approved mapping and a 20-row source shape
missing `status`; run `DEMO1` directly to produce
`BATCH_FATAL` at the file quality gate before row-level quarantine.
The Reconciliation tab defaults to partner `DEMO` and the current business
date, and exposes the existing manual reconciliation control.

The scheduler-first cases are:

| Demo case | UI flow |
|---|---|
| `DEMO-VALID-001-TX` | persists and is included when reconciliation continues |
| `DEMO-DUPLICATE-001-TX` | high-priority conflict; claim, inspect, and resolve |
| `DEMO-MISSING-AMOUNT-001-TX` | row-level missing required `amount`; review and choose reject or reprocess |
| `DEMO-VALID-002-TX` … `DEMO-VALID-018-TX` | ordinary rows available for reconciliation |
| `DEMO1-BATCH-FATAL-001-TX` … `DEMO1-BATCH-FATAL-020-TX` | run `DEMO1` from Schedules; missing `status` stops the batch before row quarantine |

The deterministic domain fixture `build_demo_quarantine_records()` remains
available for isolated UI/action contract tests covering invalid rows,
accept-existing, rejection, escalation, and source-unit recovery. It is not
the scheduler-first live seed. Reset is scoped to partner `DEMO` and rewrites
only local demo source and persistence fixtures for `DEMO` and `DEMO1`; it is not a production data
reset. The UI deliberately renders lifecycle metadata, stable error codes,
sanitized evidence, and bounded resolution history only; raw rows, credentials,
fingerprints, parsed timestamps, and full exceptions remain unavailable.

The browser smoke contracts are:

```bash
npm --prefix frontend-next run lint
npm --prefix frontend-next run typecheck
npm --prefix frontend-next run build
npm --prefix frontend-next run test:e2e -- e2e/quarantine-review.spec.ts --workers=1
npm --prefix frontend-next run test:e2e -- e2e/quarantine-demo-live.spec.ts --workers=1
```

The live demo test checks the real seeded API and the browser redaction
boundary. It is local mock-data evidence only and must not be represented as
staging or production acceptance.

## Acceptance matrix

| Gate | Required evidence | Demo status |
|---|---|---|
| B quality accounting | Contract tests and a sanitized run showing input/persisted/rejected/duplicate/quarantine counters reconcile | Demo pass |
| C normalization/validation | Focused parity tests plus the existing full-dataset v2 artifact | Demo pass |
| D quarantine/recovery | Mock source-row replay, conflicting-duplicate hold, checkpoint-safe resume, and no duplicate persistence | Demo contract pass |
| E operator flow | Claim race, stale status, wrong owner, reprocess, accept-existing, reject, escalation, idempotent replay, audit and redaction | Demo contract pass |
| Runtime topology | Compose health, migration/index readiness, Airflow DAG readiness, source path and PostgreSQL/Mongo persistence | Local Compose pass |
| Partner acceptance | Partner confirms expected quality outcomes | Not required for demo |
| Cutover readiness | Production rollback, secret handling, and production owner | Out of scope |

## Required scenarios

Execute these scenarios using the existing fixtures, API namespace, and
runbooks. Record only bounded outcomes, counters, statuses, checkpoint state,
sanitized correlation IDs, and audit counts.

| Scenario | Expected result |
|---|---|
| Clean baseline | `PASS / CONTINUE / INGESTED`; counters reconcile and no quarantine row is created |
| Ordinary invalid row | `REVIEW / CONTINUE`; valid rows persist and the invalid row is quarantined |
| Conflicting duplicate | `REVIEW / HOLD_FOR_REVIEW`; the source unit remains blocked until resolution |
| Source-unit recovery | Retry/resume starts from the durable checkpoint, preserves prior rows, and does not replay the same conflict |
| Claim race | Exactly one operator acquires the lease; the loser receives a bounded conflict |
| Reprocess and accept-existing | The current claimant is required; source authority/fingerprint verification stays internal |
| Reject and escalation | Reject requires a bounded reason; escalation preserves status/owner and stops at level 3 |
| Action replay | Same `(recordId, actionId)` returns the bounded prior result without a second transition or audit event |
| Redaction | API, audit, and evidence contain no raw row, credential, full exception, parsed timestamp, or fingerprint |

## Execution sequence

1. Prepare the local Compose demo environment from the current artifact. Verify
   mock data, `APP_AUTOMATION_ORCHESTRATOR=local` when Airflow is not running,
   and no duplicate scheduler is enabled. Use `airflow` instead when running
   the full topology contract.

2. Run the automated regression and static gates:

   ```bash
   uv run pytest -q --tb=short
   uv run pytest \
     tests/test_quality_contract.py \
     tests/test_normalizer.py \
     tests/test_ingestion_pipeline.py \
     tests/test_quarantine_lifecycle.py \
     tests/test_quarantine_service.py \
     tests/test_quarantine_actions.py \
     tests/test_quarantine_audit.py \
     tests/test_api_quarantine.py \
     tests/test_api_operations.py \
     tests/test_api_audit.py \
     -q --tb=short
   uv run ruff check src dags scripts cli tests
   uv run mypy src --show-error-codes --no-incremental
   docker compose config --quiet
   ```

3. Run the existing full topology contract against Compose. Use the exact
   service set and teardown command from [`CI-MAP.md`](../CI-MAP.md#full-topology-contract),
   then execute `tests/test_topology_contract.py --e2e -v --tb=short`. Capture
   readiness, Airflow correlation, checkpoint, MongoDB and PostgreSQL results
   without committing raw logs or credentials.

4. Execute the required scenarios above from `make quarantine-demo-run`, then
   approve the generated packet and follow its quality-gate handoff. Confirm
   that normal/fast B/C outcomes, source-backed replay, row-level ownership,
   grouped quarantine, automatic post-approval continuation, and
   mapping/`ReviewPacket` boundaries remain unchanged.

5. Complete the demo review. Record scope, decision, reviewer, timestamp,
   accepted outcomes, rejected assumptions, open blockers, and sanitized
   evidence references. Production partner approval is not inferred from this
   demo result.

## Decision rules

- `GO (demo-only)` requires all automated gates, local topology scenarios, P0
  data-integrity checks, and redaction checks.
- `NO-GO` is required for data loss, duplicate persistence, incorrect B/C
  outcome, broken checkpoint ordering, ownership bypass, sensitive-data
  exposure, or a failed demo flow.
- Production `GO` requires a separate staging/production acceptance process;
  this document does not provide that sign-off.

## Sprint 4 handoff

Deliver the sanitized F package with:

- B/C/D/E outcomes, stable error codes, quality counters, and known baselines;
- quarantine status, priority, SLA, escalation, audit, and redaction fields;
- bounded identifiers needed to correlate a run, source unit, file, and action;
- acceptance gaps and partner decisions that Sprint 4 must not infer;
- open observability decisions: alert thresholds, notification targets,
  dashboard views, stage metrics, and the 100k observability threshold.

Sprint 4 remains the owner for implementing those observability capabilities.
