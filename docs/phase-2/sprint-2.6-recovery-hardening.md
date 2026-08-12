# Sprint 2 / 2.5 Recovery Hardening

**Branch:** `fix/sprint2-airflow-recovery-hardening`  
**Status:** Implementation and automated verification complete; live rollout evidence remains environment-dependent
**Owner:** Platform/ingestion team

This document tracks the implementation of the global review findings from
Sprint 2 and Sprint 2.5. It is intentionally separate from the historical
Sprint 2 evaluation report so that code changes and verification evidence stay
traceable.

## Priority map

| Priority | Finding mapped from review | Acceptance criterion | Status |
|---|---|---|---|
| P0 | APScheduler and Airflow can both be active | One explicit scheduler owner per Compose mode; no duplicate daily trigger | ✅ code/tests |
| P0 | Durable staging failure has no checkpoint/event timeline | Page-fetch failure before checkpoint still appears in Recovery details | ✅ code/tests |
| P0 | Same/new runtime retry hides previous attempt evidence | Recovery drawer shows retry requested, failed/retry, and final outcome across recent runtime runs | ✅ code/tests |
| P1 | Review scope reads only the first API page | Three-page stream reports all staged record counts | ✅ code/tests |
| P1 | Approved API mapping bypasses packet and reconciles each page separately | Every durably staged paginated stream waits for scope review; approval replays all pages under one file ID and reconciles once | ✅ code/tests; live rerun pending |
| P1 | Internal DB count/evidence loses timezone semantics | Business-day query converts Asia/Ho_Chi_Minh bounds to UTC before SQL and packet stores bounded internal samples | ✅ code/tests |
| P1 | Airflow selection/config errors can leave runtime queued | Manual runtime becomes `FAILED` with an actionable error code | ✅ code/tests |
| P2 | Native Airflow retry condition is hard-coded to try 1 | Retry behavior follows configured Airflow retry budget | ✅ code/tests |
| P2 | Live Airflow service health is not covered by code tests | Runbook contains server-level verification and explicit evidence state | ⏳ |

## 2026-08-11 review update

The implementation review also corrected cross-layer contracts that were not
covered by the original recovery checklist:

- Partner business-key precedence is now normalized consistently across Python,
  SQL joins, delete filters and source-file scoping. Blank and whitespace-only
  values fall through to `vspTransId` and `partner_id`.
- PostgreSQL persistence converts aware timestamps to UTC-naive values. The
  configured business date remains a local calendar boundary.
- SQL status normalization is computed once in CTEs, result/evidence reads have
  deterministic ordering, and migration `0003` adds the composite indexes used
  by the reconciliation filters.
- Scope classification no longer exposes an unused changed-key branch and does
  not invoke the LLM when deterministic key evidence already decides the scope.
- GridFS payload cleanup covers metadata races after upload.

## Intended flow after hardening

```text
Operator/API
  -> one selected orchestrator (Airflow OR APScheduler)
  -> runtime QUEUED + correlation
  -> Airflow select_streams / mapped run_stream
  -> fetch and durable raw staging
  -> runtime attempt event (start/progress/failure/success)
  -> checkpoint + source-unit ingestion when eligible
  -> review packet or reconciliation
  -> terminal runtime status with retained attempt history
```

`WAITING_REVIEW` remains a valid business gate. Missing/stale mappings require
mapping approval; a durably staged paginated API stream with an approved mapping
also waits for the operator's scope decision. In both cases the packet retains
the same `rawStageKey`, so approval replays the complete stream as one logical
reconciliation file.

## Final automated verification — 2026-08-11

- Backend: `1056 passed, 14 skipped`.
- Ruff: passed for `src`, `dags`, `scripts` and `tests`.
- Mypy: passed for `src`, `dags` and `scripts`.
- Dependencies: `uv pip check` and `uv lock --check` passed.
- Compose: `docker compose config --quiet` passed.
- Frontend: lint, typecheck and `next build --webpack` passed.
- Frontend Playwright smoke suite: `4 passed` in production mode.
- Documentation: project-local Markdown targets checked with no broken file
  targets; source references using `#L<line>` fragments resolve to existing
  files.
- Codegraph refreshed after structural changes: 407 indexed files, 5,940
  nodes and 15,247 edges; status is up to date.

## Progress log

### 2026-08-10 — Review baseline

- Codegraph checked directly: readable SQLite index, 392 files, index current.
- Context7 `/apache/airflow` consulted for Airflow 3 deployment, dynamic task
  mapping, retries, task clearing, and mapped task-instance endpoints.
- Baseline verification: backend `1004 passed, 14 skipped`; frontend lint has
  0 errors and 2 existing warnings; typecheck passed; Compose config passed.
- Live Docker/Airflow/Mongo/PostgreSQL execution remains unverified in this
  workspace.

### Implementation updates

- [x] P0 scheduler ownership — Compose defaults to Airflow; APScheduler is an explicit profile/rollback owner.
- [x] P0 attempt/recovery history — runtime attempts are appended and exposed through Recovery events.
- [x] P1 review counts/timezone/runtime failure propagation — raw-stage totals, UTC-normalized business-day bounds and internal review evidence are covered.
- [x] P1 stream-scoped Mapping evidence — Review Packet keeps the stream reference while the Mapping step reads all retained raw records in bounded pages. `sourceUnitKey`, page and global stream row identity are shown to the reviewer.
- [x] P2 Airflow retry/runbook hardening — retry default is manual-only (`AIRFLOW_TASK_RETRIES=0`) and Airflow-side terminal errors are explicit.
- [x] Automated final verification and codegraph status; live container rollout remains environment-dependent.

### 2026-08-11 — Full-stream Mapping implementation

- Added `GET /api/v1/review-packets/{packet_id}/raw-records?offset=0&limit=50`.
  The endpoint resolves pages by the packet's `rawStageKey`, reads payloads from
  retained raw staging/GridFS, and returns bounded rows with `streamRowIndex`,
  `rowIndex`, `page`, and `sourceUnitKey` provenance.
- Guided Review Mapping now renders the complete retained stream through a
  paginated table. It does not copy the full payload into Mongo Review Packet
  metadata or load the entire stream into the browser at once.
- Runtime validation now consumes every retained page in the packet stream when
  `rawStageKey` is present. Approval/replay already uses the same scope, so the
  stream inspected during Mapping is the stream that is replayed after approval.
- Regression evidence: `30 passed` across Review Packet API, raw-stream reader,
  runtime full-stream validation, and architecture tests; targeted Ruff passed;
  frontend `typecheck` passed and `lint` has 0 errors (2 pre-existing font warnings).
- Final verification on 2026-08-11: `.venv/bin/pytest -q` returned `1025 passed,
  14 skipped`; frontend `npm run build` completed successfully; codegraph sync
  processed 11 changed files and `codegraph status` reports the index up to date.
- Live diagnosis on 2026-08-11: restarting the API alone did not deploy the
  new source because the Compose service uses a baked image. After
  `docker compose build api && docker compose up -d api`, the container
  contains `review_raw_stream.py` and exposes the raw-record endpoint.
- The current live VIETTELPAY database has an `APPROVED` mapping and its latest
  run is `COMPLETED`; therefore `review_packet` and `pendingReviewPackets` are
  correctly `0`. To produce a Review Packet, run a new source structure with
  no matching approved mapping (or a changed/stale structure); creating a
  packet for an already approved mapping would violate the mapping gate.
- Recovery now returns `requestAttemptCount` and annotates every event with
  `requestAttempt`, so the UI explicitly renders `Request 1/3`, `Request 2/3`,
  and so on instead of only showing the checkpoint's per-unit attempt count.
- Schedules UI now has a Partner dropdown populated from the live job list,
  including VIETTELPAY. The Recovery drawer is fetch-only: it keeps request
  attempts, fetch-unit timeline, cursor/retry/error controls, and removes
  ingestion/reconciliation counters and runtime-ingest sections.
- Logical reconciliation batch hardening is now implemented for approved
  Review Packet replay. The three raw pages remain independently retained under
  one rawStageKey, while the first successful page becomes the single
  batch-level reconciliation_file. Transactions from subsequent pages are
  rebound to that same sourceFileId; their temporary page file claims are
  removed.
- Reconciliation is invoked once, only after every staged page succeeds. The
  batch metadata records pageCount, processedPageCount, pageIds,
  expectedRowCount, and actualRowCount. A failed page deletes the partial
  canonical rows, marks the logical file failed, leaves raw pages replayable,
  and does not invoke reconciliation.
- Required batch invariants are: 3 raw pages with one rawStageKey, 1 logical
  reconciliation_file, 6 partner rows sharing one sourceFileId, and one
  reconciliation run returning all 6 results. The regression suite covers both
  the successful three-page path and the failed-middle-page path.
- Design and execution references:
  [`docs/superpowers/specs/2026-08-11-full-stream-review-mapping-design.md`](../superpowers/specs/2026-08-11-full-stream-review-mapping-design.md)
  and [`docs/superpowers/plans/2026-08-11-full-stream-review-mapping.md`](../superpowers/plans/2026-08-11-full-stream-review-mapping.md).

### 2026-08-11 — Scheduler scope-gate correction

- Live runtime `9bd4d053-83fb-474d-a54b-0724f3de444a` proved the previous
  logical-batch implementation covered only post-approval replay. Because the
  ViettelPay mapping was already `APPROVED`, the scheduler bypassed the packet,
  created one file per page, and reconciliation exposed only the final page's
  two rows.
- Paginated API streams that have durable raw staging now always create or
  refresh a scope Review Packet after all pages are fetched. The runtime stops
  at `WAITING_REVIEW` with the stream `rawStageKey`; no page is ingested or
  reconciled before the operator selects scope and validates the mapping.
- **Approve keep current** now queues the same post-approval batch replay for
  the packet's approved runtime mapping. Thus it preserves the mapping while
  producing one logical `reconciliation_file`, one `sourceFileId`, and one
  reconciliation execution across every raw page.
- Regression evidence: targeted Ruff passed; `46 passed` across staged-page,
  scheduler, review-packet, raw-stream, and logical-batch tests. A new live
  ViettelPay run is still required to validate UI/Compose deployment.

### 2026-08-11 — ViettelPay Review Packet demo mode

- `make viettelpay-sprint2-reset` now seeds the ViettelPay fetch configuration
  and six internal rows, but deliberately creates no approved mapping. The
  next Run Now fetches/stages all three pages and stops at a Review Packet,
  making the scope/mapping flow reproducible from the UI.

### 2026-08-11 — Internal evidence timezone correction

- BSON/Motor returns stored UTC instants as naive datetimes. Review evidence,
  scope classification, and reconciliation now interpret such values as UTC
  before deriving the configured business day; this prevents a midnight ICT
  seed from being queried as the prior local day.
- The pending ViettelPay packet was backfilled and now contains
  `internalRecordCount: 6` plus six bounded internal preview records.

### 2026-08-11 — Generic object-source mapping correction

- AI mapping generation remains column-based for tabular sources, but now
  derives object references from the detected source representation: JSON,
  JSONL, and NDJSON mappings use the discovered header/key as `sourceField`.
  This is generic to the reader contract and does not contain partner-specific
  names.
- The Guided Review Mapping step now treats a `sourceField` as a real source
  reference, including mapped status fields, and labels it explicitly. The
  retained raw-stream table remains the sample evidence for all staged pages.
- Runtime validation now preserves dictionary rows for mappings that contain
  `sourceField`; legacy column mappings still receive positional list rows.
  The live ViettelPay packet was revalidated successfully: `6/6` sampled rows,
  `0` failed, validation state `CURRENT`.

### 2026-08-11 — Business-date and file-level packet evidence correction

- Confirmed the date boundary: Airflow commands already carry the configured
  business date, while the legacy daily runner now derives local midnight from
  `settings.business_timezone`. Review evidence treats Mongo BSON-naive
  timestamps as UTC and converts them to the configured business day before
  querying PostgreSQL. The Review Center now formats the packet date in
  `Asia/Ho_Chi_Minh`, so a stored `17:00Z` instant is displayed as the next
  business date instead of the previous UTC calendar date.
- FileDrop/SFTP review packets do not have an API `rawStageKey`; their review
  scope is one source file. `GET /review-packets/{id}/raw-records` now reads
  that packet's `sourceFilePath` with bounded pagination and resolves the
  `/opt/airflow/app` ↔ `/app` container path mapping. A packet that combines a
  file-level source with a metadata-only `rawStageKey` is invalid mock data and
  is rejected; API packets with retained pages continue to read the complete
  GridFS/raw-page stream by `rawStageKey`.
- Guided Review shows a bounded partner sample immediately on the Scope step
  and the complete file/stream records on Mapping. Internal DB evidence remains
  behind the eye icon. Recovery summary hides a recovery badge when it is only
  a mirror of the runtime `RUNNING`/`WAITING REVIEW` status; unit-level error,
  retry, cursor and completion details remain visible.
- Verification: `42 passed` across review-packet/raw-stream/scheduler tests;
  frontend typecheck and targeted lint pass.

### 2026-08-10 — Implementation evidence

- Targeted regression: `52 passed` across Airflow deployment/runtime, recovery,
  stream execution, review scope, timezone and runtime-history tests.
- TestClient workaround regression: API suites `68 passed` after switching
  synchronous endpoint tests to the `httpx2` ASGI transport facade.
- Static quality: targeted Ruff pass.
- Live Docker verification (2026-08-10, after restart): Airflow API, Airflow
  scheduler,
  DAG processor, MongoDB and PostgreSQL are healthy/running; API OpenAPI returns
  HTTP 200; API ownership is `airflow`; `AIRFLOW_GLOBAL_SCHEDULE=none`; and no
  legacy `reconciliation-scheduler` container is running. DAG import errors are
  empty. Infrastructure ownership gate: ✅.
- Live verification after the manual-only/review-evidence image rebuild:
  `AIRFLOW_TASK_RETRIES=0`, `AIRFLOW_GLOBAL_SCHEDULE=none`, API imports
  `review_evidence`, Airflow health is healthy, DAG import errors remain empty,
  `pip check` reports no broken requirements, `paramiko=3.5.1` satisfies the
  Airflow SFTP/SSH provider constraint, and OpenAPI returns HTTP 200. Runtime
  rollout gate: ✅.
- Business-flow acceptance gate: ✅ manual page-2 failure/retry/recovery and
  partner/internal row-count verification passed live. Guided-review packet
  rendering remains a separate mapping-gate scenario when a packet is pending.

### 2026-08-10 — Manual-only retry and review evidence hardening

- Airflow and Compose defaults now use `AIRFLOW_TASK_RETRIES=0`; the failed
  mapped task remains terminal until the operator clicks **Retry now**.
- Recovery events now merge checkpoint events with attempt history from recent
  runtime documents and deduplicate by `eventId`. This preserves sequences such
  as `page 1 COMPLETED -> page 2 FAILED -> RETRY_REQUESTED -> page 2 COMPLETED -> page 3 COMPLETED`, including fallback retries that create a new runtime document.
- Review packets now persist `internalRecordCount` and a bounded
  `internalPreview` from PostgreSQL. The Scope step renders that evidence next
  to the partner sample. Existing packets are backfilled when scope
  classification runs.
- Internal review queries use the configured business timezone before the
  repository converts bounds to the PostgreSQL UTC-naive convention.
- Manual Airflow retry now sends `reset_dag_runs=true` when clearing a mapped
  task. Airflow 3 otherwise clears the task but leaves a terminal DagRun in
  `FAILED`, so the scheduler never starts the operator retry. If an earlier
  clear left the task state `null`, the gateway falls back to the parent
  DagRun state and can repair it safely.

### 2026-08-10 — Live manual-retry acceptance

- Reproduced the stuck VIETTELPAY runtime from
  `manual__4286f4d1-b24f-40b9-8992-c2b44410e0fa`: the first attempt failed on
  page 2, the old retry cleared the task while leaving the DagRun terminal,
  and no second `stream_execution_started` event appeared.
- After the gateway fix, the same manual retry ran successfully: 3/3 source
  units completed, 6/6 partner rows were ingested, and Recovery showed the
  complete `FAILED -> RETRY_REQUESTED -> STARTED -> PROCESSING/COMPLETED ->
  COMPLETED` timeline.
- Live Airflow confirms `AIRFLOW_TASK_RETRIES=0`,
  `AIRFLOW_GLOBAL_SCHEDULE=none`, `run_stream.retries=0`, and
  `dagSchedule=None`. The observed `tryNumber=2` is the explicit operator
  retry, not native automatic retry.
- PostgreSQL contains 6 VIETTELPAY partner rows and 6 VIETTELPAY internal rows
  for the same Asia/Ho_Chi_Minh business day. No new review packet is expected
  for this run because the approved mapping completed normally; mapping-gated
  runs use the guided-review packet path and its internal preview.
- A live manual reconciliation after the timezone fix completed with
  `reconciliationCount=6`; the reconciliation API returned `MATCHED` rows with
  non-null `internalTxnId` and matching partner/internal amounts. This confirms
  `COMPLETED` is the hand-off point for opening reconciliation results, while
  validation remains a separate operator step.
- The Sprint 2 demo seed intentionally creates an `APPROVED` mapping. Therefore
  the UI **Run Now -> page-2 failure -> Retry** scenario validates recovery and
  ingestion, but it does not validate Review Center creation. To validate a
  packet interactively, use a missing/stale mapping scenario (for example a
  changed source structure or a new partner mapping), then wait for the run to
  reach `WAITING_REVIEW`; only then should `pendingReviewPackets` become `1`.
- Reconciliation results are generated once after all pages in the logical
  source batch are successfully ingested. New results are scoped by the shared
  runtime run ID and logical sourceFileId; legacy rows without a run ID remain
  visible through a partner/date fallback. Reconciliation date boundaries use
  `APP_BUSINESS_TIMEZONE` so UTC-stored internal records are matched against
  the same business day as partner data.

### 2026-08-11 — Key-based scope and batch-only reconciliation

- Scope classification no longer reads filename tokens such as `settlement`,
  `phase`, `batch`, or `replacement`. The decision is based on normalized
  business-key overlap, historical-key coverage, new-key ratio, and changed
  overlapping payload evidence.
- `INCREMENTAL_APPEND` is batch-only: the current source file is reconciled
  and displayed by its own `sourceFileId`; prior same-day batches remain
  untouched and are not unioned into the current result view.
- A file that covers 100% of the historical same-day key set and adds new
  keys is classified as `REPLACEMENT`. This represents a superseding
  delivery and is processed as the complete current file, while stale results
  for overlapping keys are removed safely.
- `FULL_SNAPSHOT` remains the only scope that replaces the entire partner/date
  result slice. Ambiguous key evidence returns `UNCONFIRMED` for operator
  review rather than guessing from naming.

### Scheduler ownership and local startup

### Ordered FileDrop backfill operator path

The current branch also exposes a VNPAY FileDrop backfill from Schedules. The
operator selects an inclusive date range; the API persists one `backfill_run`
parent and submits one Airflow DAG run in `mode=BACKFILL`. Airflow processes
business dates in ascending order, records per-day progress, and never shares
the scheduled checkpoint. If mapping approval is required, Guided Review
resumes the same parent after approval instead of creating a second
post-approval run. Reproduce the local fixture with
`make vnpay-backfill-reset`.

The default Compose stack uses Airflow as the application orchestrator and
keeps the Airflow DAG manual-only unless `AIRFLOW_GLOBAL_SCHEDULE` is set.
The manual-pilot deployment has no legacy scheduler service. Airflow is the
only workflow owner and the DAG remains manual-only until a separate schedule
cutover decision.

```bash
docker compose up -d postgres mongodb sftp airflow-api-server airflow-scheduler airflow-dag-processor api
```

Do not introduce a second scheduler owner for the same stream. Rollback requires
pausing the DAG and deploying the previous application artifact; it does not
re-enable a removed APScheduler service.

### Live acceptance evidence to collect

```bash
curl --fail http://localhost:8080/api/v2/monitor/health
docker compose exec airflow-api-server airflow dags list-import-errors
docker compose logs --tail 120 airflow-scheduler airflow-dag-processor
```

Then execute one manual ViettelPay run with the page-2 failure fixture and one
VNPAY ordered backfill. Record: `runtimeRunId`, parent `backfillRunId`, Airflow
`dagRunId`, Recovery event timeline, ordered day statuses, review packet count,
raw-stage `itemCount` total, and PostgreSQL internal-transaction count for the
same Asia/Ho_Chi_Minh business date.

## Verification commands

```bash
rtk proxy .venv/bin/pytest -q
rtk proxy .venv/bin/ruff check src dags scripts tests
rtk proxy .venv/bin/mypy src dags scripts
npm --prefix frontend-next run lint
npm --prefix frontend-next run typecheck
rtk proxy docker compose config --quiet
rtk codegraph status
```

The live acceptance run must additionally verify Airflow health, DAG parsing,
manual Run Now, page-2 failure, Retry now, review packet counts, and PostgreSQL
internal-row counts against the same business date.
