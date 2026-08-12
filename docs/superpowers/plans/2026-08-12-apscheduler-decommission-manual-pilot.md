# APScheduler Decommission — Manual Airflow Pilot Implementation Plan

> **Status:** Completed for the manual Airflow pilot on 2026-08-12. Steps use checkbox (`- [x]`) syntax for completed work.

**Goal:** Chuyển hệ thống sang Airflow làm owner duy nhất cho manual pilot, xác minh manual run/retry/backfill an toàn, rồi mới loại bỏ APScheduler legacy mà không xóa ingestion runner đang được Airflow sử dụng.

**Architecture:** API và các thao tác UI submit qua `AirflowWorkflowGateway`; DAG `reconciliation_ingestion` giữ orchestration, còn `src/scheduler/jobs.py` tạm thời giữ vai trò application ingestion runner. Sau khi pilot có evidence, control plane APScheduler được xóa và daily cron vẫn để riêng cho một acceptance decision khác.

**Tech Stack:** FastAPI, Apache Airflow 3.3 LocalExecutor, MongoDB, PostgreSQL, Docker Compose, pytest, Ruff, codegraph.

## Global Constraints

- `AIRFLOW_GLOBAL_SCHEDULE=none` trong manual pilot; không bật daily cron trong scope này.
- Không có scheduler control plane thứ hai chạy đồng thời với Airflow.
- Không xóa `src/scheduler/jobs.py` trong đợt này vì Airflow vẫn import `run_fetch_config_once`.
- Không reset checkpoint, runtime run hoặc reconciliation data khi restart/rebuild.
- Mọi thay đổi cấu trúc phải được kiểm tra lại bằng codegraph trước khi kết luận.

---

### Task 1: Lock manual pilot ownership to Airflow (completed)

**Files:**
- Modify: `src/config/settings.py:20`
- Modify: `tests/test_airflow_runtime.py`
- Modify: `tests/test_airflow_deployment.py`
- Modify: `.env.example:26-37`

**Interfaces:**
- Consumes: `settings.automation_orchestrator`, `AirflowWorkflowGateway`, `cli.scheduler.apscheduler_is_owner`.
- Produces: default configuration that selects Airflow and explicitly keeps the DAG manual-only.

- [x] **Step 1: Add a regression assertion for Airflow as the application default.**

  Assert that a freshly constructed `Settings` uses `automation_orchestrator == "airflow"` when no environment override is present. Preserve the explicit `apscheduler` owner-switch test only as a temporary rollback contract.

- [x] **Step 2: Run the focused configuration tests and verify the current default fails.**

  Run: `rtk proxy uv run pytest -q tests/test_airflow_runtime.py tests/test_airflow_deployment.py`

  Expected before implementation: the new default assertion fails because `src/config/settings.py` currently defaults to `apscheduler`.

- [x] **Step 3: Change only the settings default to Airflow.**

  Change `automation_orchestrator` from `"apscheduler"` to `"airflow"`; do not remove the Literal value or the rollback branch yet.

- [x] **Step 4: Make the manual-only pilot contract explicit in `.env.example`.**

  Keep `APP_AUTOMATION_ORCHESTRATOR=airflow` and `AIRFLOW_GLOBAL_SCHEDULE=none`, and document that changing the schedule is out of scope until pilot acceptance.

- [x] **Step 5: Run the focused tests and lint.**

  Run: `rtk proxy uv run pytest -q tests/test_airflow_runtime.py tests/test_airflow_deployment.py`

  Run: `rtk proxy uv run ruff check src/config/settings.py tests/test_airflow_runtime.py tests/test_airflow_deployment.py`

  Expected: all focused tests and Ruff checks pass.

---

### Task 2: Verify manual pilot in Docker without legacy scheduler (completed)

**Files:**
- Modify: `docs/phase-2/sprint-2.5-airflow-migration.md`
- Modify: `README.md` only if observed commands or status are stale

**Interfaces:**
- Consumes: Airflow ownership from Task 1, `docker-compose.yml`, `dags/reconciliation_ingestion.py`, VNPAY FileDrop fixture, MOMO/ViettelPay fixtures.
- Produces: reproducible evidence for manual run, mapping approval, retry, backfill, restart and no duplicate legacy owner.

- [x] **Step 1: Validate the resolved Compose configuration.**

  Run: `docker compose config --quiet`

  Confirm the default service set does not start `scheduler`, while Airflow API server, scheduler and DAG processor remain present.

- [x] **Step 2: Rebuild and restart only the Airflow/API path.**

  Run: `docker compose build api airflow-api-server airflow-scheduler airflow-dag-processor`

  Run: `docker compose up -d --no-build postgres mongodb sftp api airflow-api-server airflow-scheduler airflow-dag-processor`

  Confirm with `docker compose ps --all` that Airflow services are healthy/up and `reconciliation-scheduler` is not running.

- [x] **Step 3: Execute the manual VNPAY FileDrop backfill pilot.**

  Run the existing `make vnpay-backfill-reset`, create the inclusive date-range backfill through the UI/API, approve the mapping in Guided Review, and observe the Backfill progress panel until all dates reach terminal status.

  Verify: parent run completes, each business date has one child runtime run, mapping version remains pinned, PostgreSQL result counts/statuses are stable, and no second post-approval run is created.

- [x] **Step 4: Exercise manual retry and restart behavior.**

  Use the existing ViettelPay failure/recovery fixture or equivalent manual run. Verify Airflow task state, runtime attempt history, checkpoint resume, and final row count after retry. Restart API, Airflow scheduler and DAG processor once, then confirm the same manual flow still submits through Airflow.

- [x] **Step 5: Capture the pilot evidence in the Airflow migration runbook.**

  Record the date, service state, DAG run IDs, runtime/backfill IDs, result counts, and the fact that `AIRFLOW_GLOBAL_SCHEDULE=none` intentionally means no automatic daily schedule.

---

### Task 3: Remove APScheduler control plane after pilot evidence (completed)

**Files:**
- Delete: `cli/scheduler.py`
- Delete: `src/scheduler/scheduler.py`
- Delete or simplify: `src/scheduler/config.py` after reference scan
- Modify: `run.py`
- Modify: `docker-compose.yml`
- Modify: `tests/test_airflow_deployment.py`
- Modify: `tests/test_airflow_runtime.py`
- Modify: `tests/test_scheduler_source_units.py` only where it imports the deleted control-plane classes
- Modify: `Makefile`

**Interfaces:**
- Consumes: pilot evidence from Task 2; `src/scheduler/jobs.py` remains the runner boundary.
- Produces: no APScheduler service, CLI startup path, Mongo job store or dependency in the default application.

- [x] **Step 1: Run a reference scan before deleting anything.**

  Run: `rtk rg -n "PartnerDataScheduler|SchedulerConfig|handle_scheduler_mode|apscheduler_jobs|--start-scheduler|--list-jobs|--run-job-now|apscheduler" src cli run.py docker-compose.yml Makefile tests docs README.md requirements.txt pyproject.toml`

  Classify every match as control-plane code, runner compatibility, test, or documentation. Keep only runner compatibility until a later rename task.

- [x] **Step 2: Add/update architecture tests that Airflow execution imports without APScheduler.**

  Retain the guarded import test for `src.scheduler.jobs.run_fetch_config_once`; replace tests that require the deleted daemon with assertions that no Compose service or CLI option starts it.

- [x] **Step 3: Remove the legacy Compose service/profile and CLI dispatch.**

  Remove the `scheduler` service and `apscheduler` profile from Compose. Remove scheduler parser options and the `cli.scheduler` dispatch branch from `run.py`, while leaving ingestion and reconciliation CLI modes intact.

- [x] **Step 4: Remove the APScheduler daemon/config implementation and dependency only after the reference scan is clean.**

  Delete `cli/scheduler.py`, `src/scheduler/scheduler.py`, and unused scheduler config/dependency entries. Do not alter `run_fetch_config_once`, `daily_partner_fetch_job` until a separate runner renaming task has tests.

- [x] **Step 5: Update Makefile, README and migration docs.**

  Remove legacy start/list/run commands and rollback instructions. State that manual pilot rollback is an application/DAG pause procedure, not APScheduler reactivation. Keep historical references labeled as historical.

- [x] **Step 6: Run structural verification.**

  Run: `rtk proxy uv run pytest -q tests/test_airflow_deployment.py tests/test_airflow_runtime.py tests/test_api_automation.py tests/test_workflow_gateway.py`

  Run: `rtk proxy uv run ruff check src cli dags tests`

  Run: `docker compose config --quiet`

  Run: `rtk rg -n "PartnerDataScheduler|SchedulerConfig|apscheduler_jobs|--start-scheduler|apscheduler" src cli run.py docker-compose.yml Makefile requirements.txt pyproject.toml`

  Expected: no active legacy control-plane references; only intentionally historical documentation references may remain.

---

### Task 4: Refresh repository graph and final manual-pilot verification (completed)

**Files:**
- Modify: `docs/phase-2/sprint-2.5-airflow-migration.md`
- Modify: `README.md` if the final structure changed

**Interfaces:**
- Consumes: Tasks 1–3 and all focused/full verification results.
- Produces: current codegraph, accurate root documentation, and a bounded handoff for the later automatic-schedule cutover.

- [x] **Step 1: Refresh and inspect codegraph.**

  Run the repository codegraph sync command, then `rtk codegraph status`. Confirm the index is complete and includes the final file count/scope.

- [x] **Step 2: Run the final backend and frontend quality gates relevant to this change.**

  Run: `rtk proxy uv run pytest -q`

  Run: `rtk proxy uv run ruff check src dags scripts tests`

  Run: `npm --prefix frontend-next run lint`

  Run: `npm --prefix frontend-next run typecheck`

- [x] **Step 3: Verify the manual-only operational contract.**

  Confirm Airflow services are up, the legacy scheduler is absent, `APP_AUTOMATION_ORCHESTRATOR=airflow`, and `AIRFLOW_GLOBAL_SCHEDULE=none`. Confirm manual Run Now, Guided Review approval, retry and VNPAY backfill remain documented and tested.

- [x] **Step 4: Mark only the completed scope in docs.**

  State explicitly that manual pilot ownership/decommission is complete only if all evidence exists; leave automatic daily scheduling as a separate follow-up task rather than implying it is enabled.
