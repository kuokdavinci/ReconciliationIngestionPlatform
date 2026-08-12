# VNPAY FileDrop Backfill UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a UI-driven, Airflow-backed VNPAY FileDrop backfill that requires mapping approval when needed and exposes ordered per-day progress in the application UI.

**Architecture:** The application owns a durable parent `backfill_run` with one day entry per business date. The API creates the parent and submits one Airflow DAG run; Airflow processes dates sequentially through the existing `execute_stream()` contract and updates the parent/day state. Guided Review receives the parent backfill context so approving a draft mapping resumes the parent backfill instead of starting an unrelated post-approval run. The Schedule page keeps a compact table and opens a Backfill dialog/progress panel.

**Tech Stack:** FastAPI, Pydantic, MongoDB/Motor, Airflow 3 DAG, Next.js/React/TypeScript, Playwright, pytest, Make.

## Global Constraints

- Preserve existing ViettelPay API recovery, MOMO FileDrop, Run Now, Retry, and Guided Review behavior.
- Backfill must use `mode=BACKFILL` and must never read or write the scheduled checkpoint.
- Dates execute strictly in ascending business-date order; a failed/blocked day prevents later days from starting.
- Mapping approval must lock the approved `configVersion` for the parent backfill; no config mixing inside one run.
- Backfill approval must not create a separate post-approval ingestion run for the same source file.
- Airflow REST/XCom payloads contain identifiers and dates only, never partner secrets.
- UI progress uses bounded polling and must show parent status plus each day status.
- New behavior follows test-first development; run targeted tests before the full validation suite.

---

### Task 1: Backfill domain, persistence, and API contract

**Files:**
- Create: `src/domain/backfill/models.py`
- Create: `src/infrastructure/backfill/repository.py`
- Create: `src/services/backfill_runs.py`
- Modify: `src/domain/runtime/models.py`
- Modify: `src/application/automation/contracts.py`
- Modify: `src/api/automation.py`
- Modify: `src/infrastructure/persistence/mongo_indexes.py`
- Test: `tests/test_backfill_runs.py`
- Test: `tests/test_api_automation.py`

**Interfaces:**
- `POST /api/v1/automation/jobs/{partner}/backfill` accepts `fromDate`, `toDate`, optional `fetchConfigId`, and creates a parent run with ordered day records.
- `GET /api/v1/automation/backfill-runs/{backfill_run_id}` returns `status`, `currentDate`, `completedDays`, `totalDays`, `configVersion`, `approvalRequired`, `days`, and Airflow correlation.
- `BackfillRunRepository.create/find/claim_day/update_day/update_status` persists the application source of truth.

- [x] **Step 1: Add failing tests for date validation and ordered day creation.**
- [x] **Step 2: Run the focused tests and confirm the missing model/service failure.**
- [x] **Step 3: Implement the Pydantic models, repository, indexes, and service helpers.**
- [x] **Step 4: Add the start/status API routes and Airflow submission boundary.**
- [x] **Step 5: Run `uv run pytest tests/test_backfill_runs.py tests/test_api_automation.py -q`.**

### Task 2: Ordered Airflow execution and approval-aware resume

**Files:**
- Modify: `dags/reconciliation_ingestion.py`
- Modify: `src/application/automation/contracts.py`
- Modify: `src/domain/review/models.py`
- Modify: `src/services/review_packet_actions.py`
- Modify: `src/scheduler/jobs.py`
- Test: `tests/test_airflow_backfill.py`
- Test: `tests/test_api_review_packets.py`

**Interfaces:**
- Backfill DAG conf carries `backfillRunId`, `fetchConfigId`, `partner`, `fromDate`, `toDate`, and `mode=BACKFILL`.
- The DAG executes one date at a time in ascending order and updates the parent/day state after each `execute_stream()` result.
- `ReviewPacket` carries optional `backfillRunId`; approval of a packet with this context approves the mapping and resumes the parent run without launching an independent post-approval run.

- [x] **Step 1: Add failing tests for strict date ordering, stop-on-failure, and resume-after-approval.**
- [x] **Step 2: Run the focused tests and verify they fail for the missing backfill execution path.**
- [x] **Step 3: Implement the Airflow backfill task and day-state updates.**
- [x] **Step 4: Propagate backfill context into review packet creation and approval.**
- [x] **Step 5: Run the focused backfill/review regression tests.**

### Task 3: Schedule UI refactor, Backfill dialog, and progress panel

**Files:**
- Create: `frontend-next/src/components/schedules/schedule-actions.tsx`
- Create: `frontend-next/src/components/schedules/backfill-dialog.tsx`
- Create: `frontend-next/src/components/schedules/backfill-progress-panel.tsx`
- Modify: `frontend-next/src/components/schedules/schedule-table.tsx`
- Modify: `frontend-next/src/components/schedules/schedules.module.css`
- Modify: `frontend-next/src/app/schedules/page.tsx`
- Modify: `frontend-next/src/lib/api/automation.ts`
- Modify: `frontend-next/src/types/schedules.ts`
- Test: `frontend-next/e2e/dashboard-interactions.spec.ts`

**Interfaces:**
- Schedule rows show partner/method, schedule/destination, runtime, recovery, and a wrapping action area without a fixed `min-width` overflow.
- `BackfillDialog` validates `fromDate <= toDate` and submits one parent backfill request.
- `BackfillProgressPanel` polls the status endpoint every 2–3 seconds, shows aggregate progress and each business date, and links the review packet when `WAITING_CONFIG`.

- [x] **Step 1: Add/extend Playwright assertions for visible Backfill action, date validation, progress states, and no action overflow.**
- [x] **Step 2: Run the focused E2E test and confirm the new UI behavior is absent.**
- [x] **Step 3: Implement the responsive row/action components and progress panel.**
- [x] **Step 4: Wire API calls, polling cleanup, approval navigation, retry, and close/reopen behavior.**
- [x] **Step 5: Run lint, typecheck, production build, and focused/full Playwright tests.**

### Task 4: VNPAY FileDrop fixture and Make workflow

**Files:**
- Create: `scripts/demo/sprint2/seed_vnpay_filedrop_backfill.py`
- Modify: `Makefile`
- Modify: `src/fetchers/filedrop_fetcher.py`
- Modify: `scripts/demo/README.md`
- Modify: `README.md`
- Test: `tests/test_vnpay_filedrop_backfill_demo.py`
- Test: `tests/test_file_source_units.py`

**Interfaces:**
- `make vnpay-backfill-reset` resets VNPAY fixture data and generates deterministic FileDrop files for a configurable date range.
- `VNPAY_BACKFILL_FROM` and `VNPAY_BACKFILL_TO` override the date range; the default end date is the current Asia/Ho_Chi_Minh business date.
- The fixture creates an enabled VNPAY FileDrop fetch config and a mapping state that allows Guided Review to be exercised before the backfill is resumed.
- FileDrop patterns support the existing date-template syntax such as `settlement_VNPAY_{date:%Y%m%d}.xlsx`, so each backfill day scans only its own delivery and never consumes future dates early.

- [x] **Step 1: Add failing tests for deterministic filenames, date range, and FileDrop config.**
- [x] **Step 2: Implement the seed/reset command without modifying the existing VNPAY audit-flow seed.**
- [x] **Step 3: Add Make target and concise UI run instructions.**
- [x] **Step 4: Run `uv run pytest tests/test_vnpay_filedrop_backfill_demo.py -q` and verify `make -n vnpay-backfill-reset`.**

### Task 5: Integrated verification and documentation evidence

**Files:**
- Modify: `docs/phase-2/sprint-2-eval-run.md`
- Modify: `docs/phase-2/sprint-2-incremental-recovery.md`
- Modify: `docs/phase-2/sprint-2.5-airflow-migration.md`
- Modify: `docs/phase-2/sprint-2.6-recovery-hardening.md`

- [x] **Step 1: Run backend focused tests and Sprint 2/review regression.**
- [x] **Step 2: Run frontend lint/typecheck, production build, and Schedule/VNPAY Playwright scenarios.**
- [x] **Step 3: Validate Compose/DAG syntax; live Docker/Airflow backfill evidence remains an explicit environment acceptance step.**
- [x] **Step 4: Refresh/check codegraph after structural changes.**
- [x] **Step 5: Update docs with exact commands, approval flow, ordered dates, and known deferred evidence.**
