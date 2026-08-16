# TODO — Airflow Application Boundary Refactor

**Goal:** Remove the remaining legacy scheduler ownership, establish `src/application` as the production use-case boundary, make FastAPI routes thin adapters, and stop scripts from importing private or obsolete runtime logic without changing ingestion, recovery, backfill, or reconciliation behavior.

**Architecture:** Use a strangler migration. First move stream identity and execution behind public application modules while retaining a one-commit compatibility facade; then delete `src/scheduler`, classify `src/services` by responsibility, and move route orchestration into injected application services. Airflow remains the only control plane and continues to call `execute_stream()`; checkpoint, raw staging, review, replay, and reconciliation contracts remain application-owned.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, MongoDB/Motor, PostgreSQL/SQLAlchemy, Apache Airflow 3.3, pytest/pytest-asyncio, Ruff, Mypy, Docker Compose, CodeGraph.

## Evidence and baseline

- `.codegraph/codegraph.db` was readable and up to date on 2026-08-13: 418 files, 6,135 nodes, and 15,790 edges.
- `src/application/automation/service.py` imports `src.scheduler.jobs.run_fetch_config_once` and `_stream_identity`; therefore Airflow still depends indirectly on the scheduler namespace.
- `src/scheduler/jobs.py::run_fetch_config_once` is the active Airflow execution engine and spans 581 lines. `daily_partner_fetch_job` has no production caller; its only indexed caller is the legacy `src/scheduler/__init__.py` export.
- `src/api/automation.py` imports private `_source_stream_key` from `src.scheduler.jobs`.
- `src/services/review_packet_actions.py` imports FastAPI `Request`/`HTTPException`, builds ingestion/reconciliation services, schedules background work, and contains application workflows of 270 and 361 lines.
- Large route handlers include `list_automation_jobs` (197 lines), `retry_automation_job` (124), `classify_scope_llm_for_packet` (261), and mapping proposal creation (180).
- `scripts/demo/sprint2/evaluation.py` imports the scheduler compatibility facade and private `_units_after_checkpoint`; benchmark scripts call lower-level engines directly.
- The root `Dockerfile` still defaults to `python run.py --start-scheduler`, although `run.py` no longer accepts that option. Compose currently uses that image only for `viettelpay-mock` and overrides its command.
- Baseline verification before this plan: 52 focused scheduler/Airflow tests passed, `git diff --check` passed, and the working tree was clean.

## Global constraints

- Airflow remains the only scheduling/workflow owner. Do not add a scheduler daemon, cron owner, or second retry owner.
- Keep `AIRFLOW_GLOBAL_SCHEDULE=none`; enabling automatic daily scheduling is outside this refactor.
- Preserve `ExecuteStreamCommand` and `ExecuteStreamResult` wire aliases used by the DAG and Airflow REST payloads.
- Preserve scheduled/backfill checkpoint isolation, stable stream/source-unit identity, durable raw-page staging, waiting-review behavior, manual retry in the same DAG run, and safe duplicate outcomes.
- Preserve existing runtime/backfill/review documents; this plan contains no destructive data migration or checkpoint reset.
- Keep the full test suite. Move or rewrite tests when ownership changes; do not delete tests to reduce LOC.
- Do not modify `frontend-next/`. Existing frontend API response shapes and status strings are compatibility contracts.
- Application/domain modules must not import FastAPI, `src.api`, or Airflow SDK packages.
- API modules may compose repositories/adapters, but decorated route functions only validate transport input, call one application boundary, and map typed errors to HTTP responses.
- Scripts must use public application contracts. Data-only fixture writers may use repositories through an explicit allowlist, but may not reproduce checkpoint, runtime, backfill, review, ingestion, or reconciliation state transitions.
- Use the existing `httpx2`/ASGI test-client workaround for endpoint tests; do not introduce Starlette `TestClient` in an async event loop.
- Use `apply_patch` for edits. Run `rtk codegraph sync` after structural moves and confirm `rtk codegraph status` is up to date.

## Target file map

| Target | Responsibility |
|---|---|
| `src/application/automation/stream_identity.py` | Pure source endpoint, stream key, raw-stage key, checkpoint filtering, and scheduled/backfill identity |
| `src/application/automation/stream_ingestion.py` | Build and execute one source-unit ingestion/reconciliation callback |
| `src/application/automation/stream_runtime.py` | Runtime attempt events and terminal stream-run persistence |
| `src/application/automation/stream_runner.py` | Fetch/stage/process one configured source stream; no global scheduling |
| `src/application/automation/job_queries.py` | Build automation job/recovery/status projections |
| `src/application/automation/job_commands.py` | Run-now, retry, resolve, and workflow-submission use cases |
| `src/application/automation/backfill_service.py` | Start, resume, and read durable parent backfills |
| `src/application/runtime/service.py` | Runtime creation, updates, attempt history, and serialization |
| `src/application/review/` | Review actions, runtime validation, evidence, raw stream reads, and post-approval reprocessing |
| `src/application/mapping/` | Mapping approval/rejection and proposal-generation workflows |
| `src/application/reconciliation/manual_runs.py` | Queue and execute manual reconciliation runs |
| `src/application/operations/queries.py` | Partner intake and ingestion operational projections |
| `src/application/explorer/queries.py` | Transaction, file, and aggregate explorer queries |
| `src/application/insights/queries.py` | Insight, discrepancy, and daily-report query orchestration |
| `src/domain/ingestion/retry_policy.py` | Pure retry classification/backoff policy |
| `src/domain/mapping/contract.py` | Pure mapping canonicalization and validation |
| `src/core/business_day.py` | Shared timezone/business-day calculations |
| `src/infrastructure/mapping/composition.py` | Build production `ConfigLoader` adapters |
| `Dockerfile.viettelpay-mock` | Dedicated mock API image; replaces the stale root scheduler Dockerfile |

---

## Phase A — Remove scheduler ownership safely

### Task 1: Move stream identity into the application boundary

**Files:**
- Create: `src/application/automation/stream_identity.py`
- Create: `tests/test_stream_identity.py`
- Modify: `src/application/automation/service.py:108`
- Modify: `src/api/automation.py:36`
- Modify: `src/scheduler/jobs.py:97-223`
- Modify: `scripts/demo/sprint2/evaluation.py:9-14`
- Modify: `tests/test_scheduler_source_units.py:119-162`

**Interfaces:**
- Produces: `fetch_source_endpoint(config: FetchConfig) -> str`
- Produces: `source_stream_key(config: FetchConfig) -> str`
- Produces: `raw_stage_key(config: FetchConfig, reconciliation_date: datetime) -> str`
- Produces: `stream_identity(config: FetchConfig, *, mode: IngestionMode = IngestionMode.SCHEDULED, reconciliation_date: datetime | None = None) -> dict[str, Any]`
- Produces: `units_after_checkpoint(units: Sequence[SourceUnitMetadata | dict[str, Any]], checkpoint: Any) -> list[SourceUnitMetadata]`
- Preserves: backfill stream key suffix `:backfill:<YYYY-MM-DD>` and legacy content-hash replay fallback.

- [ ] **Step 1: Write characterization tests against the new public module.**

  Move the current stream-identity and checkpoint-filter assertions into `tests/test_stream_identity.py` and use public names:

  ```python
  from datetime import UTC, datetime

  from src.application.automation.stream_identity import (
      source_stream_key,
      stream_identity,
  )
  from src.domain.fetch_config.models import APIConfig, FetchConfig, FetchMethod
  from src.domain.ingestion.checkpoints import IngestionMode


  def test_backfill_identity_is_date_scoped():
      fetch_config = FetchConfig(
          partner="VIETTELPAY",
          fetchMethod=FetchMethod.API,
          api=APIConfig(baseUrl="https://partner.example/settlement"),
          updatedAt=datetime(2026, 8, 13, tzinfo=UTC),
      )
      reconciliation_date = datetime(2026, 8, 13, tzinfo=UTC)
      scheduled = stream_identity(fetch_config)
      backfill = stream_identity(
          fetch_config,
          mode=IngestionMode.BACKFILL,
          reconciliation_date=reconciliation_date,
      )

      assert backfill["streamKey"] == (
          f"{source_stream_key(fetch_config)}:backfill:2026-08-13"
      )
      assert backfill["streamKey"] != scheduled["streamKey"]
  ```

- [ ] **Step 2: Run the new tests and verify the module is missing.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_stream_identity.py`

  Expected before implementation: collection fails with `ModuleNotFoundError: src.application.automation.stream_identity`.

- [ ] **Step 3: Move the pure helpers without changing payload keys or error text.**

  Implement `stream_identity.py` by moving the existing helper bodies. Use public names and retain this validation:

  ```python
  if mode == IngestionMode.BACKFILL and reconciliation_date is None:
      raise ValueError("Backfill stream identity requires reconciliation_date.")
  ```

  Do not move `_current_business_day_start`; it belongs only to the dead global daily loop.

- [ ] **Step 4: Switch every repository caller to the public application module.**

  Update `service.py`, `api/automation.py`, `scheduler/jobs.py`, and the Sprint 2 evaluation script. Remove private imports of `_source_stream_key`, `_stream_identity`, and `_units_after_checkpoint` outside the scheduler file.

- [ ] **Step 5: Run focused tests and import scan.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_stream_identity.py tests/test_stream_execution.py tests/test_scheduler_source_units.py tests/test_api_automation_status.py`

  Run: `rtk proxy rg -n "from src\.scheduler\.jobs import .*(_source_stream_key|_stream_identity|_units_after_checkpoint)" src scripts tests`

  Expected: tests pass; the scan returns no matches.

- [ ] **Step 6: Commit the pure boundary move.**

  ```bash
  git add src/application/automation/stream_identity.py src/application/automation/service.py src/api/automation.py src/scheduler/jobs.py scripts/demo/sprint2/evaluation.py tests/test_stream_identity.py tests/test_scheduler_source_units.py
  git commit -m "refactor(automation): move stream identity to application"
  ```

### Task 2: Extract the production stream runner from `src/scheduler`

**Files:**
- Create: `src/application/automation/stream_ingestion.py`
- Create: `src/application/automation/stream_runtime.py`
- Create: `src/application/automation/stream_runner.py`
- Create: `tests/test_stream_ingestion.py`
- Create: `tests/test_stream_runner.py`
- Modify: `src/application/automation/service.py:18-97`
- Modify: `src/application/automation/__init__.py`
- Modify: `src/scheduler/jobs.py`
- Modify: `tests/test_raw_page_staging.py`
- Modify: `tests/test_airflow_deployment.py`
- Delete after moving assertions: `tests/test_scheduler_source_units.py`

**Interfaces:**
- Produces: `run_source_stream(...) -> dict[str, Any]` with the same parameters and behavior as `run_fetch_config_once`.
- Produces: `run_ingestion(...) -> IngestionResult | None`, implemented through `IngestionPipeline.execute(ProcessFileCommand(...))`.
- Produces: `finish_source_stream_run(...) -> dict[str, Any]` with unchanged runtime/status/stat payloads.
- Consumes: Task 1 identity functions, `process_source_units`, fetcher factory, repositories, `ReconciliationService`, and runtime service.
- Temporary compatibility: `src.scheduler.jobs.run_fetch_config_once is run_source_stream` for one task only.

- [ ] **Step 1: Add a failing public-runner test and migrate existing behavior tests.**

  Rename the test ownership and imports while preserving all current scenarios. Add this exact contract assertion before moving the behavior tests:

  ```python
  import inspect

  from src.application.automation.stream_runner import run_source_stream


  def test_stream_runner_keeps_airflow_call_contract():
      assert list(inspect.signature(run_source_stream).parameters) == [
          "config",
          "db",
          "config_loader",
          "reconciliation_date",
          "batch_size",
          "structured_logger",
          "mode",
          "runtime_run_id",
          "orchestration",
          "mapping_config_version",
          "backfill_run_id",
          "raise_on_unexpected",
      ]
  ```

  Keep tests for API page sequencing, durable staging, waiting review, replay, row-validation fast mode, and reraising unexpected Airflow errors.

- [ ] **Step 2: Run the new tests and verify the application runner is absent.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_stream_runner.py tests/test_stream_ingestion.py tests/test_raw_page_staging.py`

  Expected before implementation: import fails for `src.application.automation.stream_runner`.

- [ ] **Step 3: Extract ingestion and runtime helpers first.**

  `stream_ingestion.py` owns `_failed_ingestion_result`, source-unit cleanup, ingestion callback construction, and pipeline execution. Build commands through the existing public contract:

  ```python
  result = await pipeline.execute(
      ProcessFileCommand(
          file_path=file_path,
          partner=partner,
          workflow_type="UPC",
          file_type=FileType.SETTLEMENT,
          reconciliation_date=reconciliation_date,
          config_version=config_version,
          fetch_unit_metadata=fetch_unit_metadata,
          enable_config_health_check=enable_config_health_check,
      )
  )
  ```

  `stream_runtime.py` owns runtime attempt event creation and terminal status persistence. Keep `WAITING_REVIEW`, `COMPLETED`, and `FAILED` mapping unchanged.

- [ ] **Step 4: Move the one-stream execution function and rename it.**

  Move the complete body of `run_fetch_config_once` to `run_source_stream`, preserving the exact twelve-parameter signature asserted in Step 1. Preserve the paginated API and file-source branches exactly; this task changes ownership and names, not algorithms.

- [ ] **Step 5: Make `execute_stream()` depend directly on `run_source_stream`.**

  Remove the dynamic scheduler import. Keep the injectable `runner` seam used by `tests/test_stream_execution.py`, but set the default explicitly:

  Import `run_source_stream`, assign `selected_runner = runner or run_source_stream`, and pass the same named arguments currently passed to `runner`: `config`, `db`, `config_loader`, `reconciliation_date`, `batch_size`, `structured_logger`, `mode`, `runtime_run_id`, `orchestration`, `mapping_config_version`, `backfill_run_id`, and `raise_on_unexpected=True`.

- [ ] **Step 6: Reduce `src/scheduler/jobs.py` to a temporary facade.**

  The complete file becomes:

  ```python
  """Temporary compatibility facade for the migrated application runner."""

  from src.application.automation.stream_runner import run_source_stream

  run_fetch_config_once = run_source_stream

  __all__ = ["run_fetch_config_once"]
  ```

  Remove `daily_partner_fetch_job`; it has no production caller and Airflow already selects enabled streams in `select_stream_commands()`.

- [ ] **Step 7: Update patch targets and Airflow deployment assertions.**

  Patch application modules in tests (`src.application.automation.stream_runner.*`, `stream_ingestion.*`, `stream_runtime.*`). Change the guarded import test to import `run_source_stream` from the application package and add a temporary assertion that the old alias points to the same function.

- [ ] **Step 8: Run the full stream/Airflow regression set.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_stream_identity.py tests/test_stream_ingestion.py tests/test_stream_runner.py tests/test_raw_page_staging.py tests/test_stream_execution.py tests/test_airflow_deployment.py tests/test_airflow_backfill.py tests/test_backfill_runs.py`

  Expected: all tests pass and Airflow imports no scheduler implementation.

- [ ] **Step 9: Commit the runner extraction.**

  ```bash
  git add src/application/automation src/scheduler/jobs.py tests/test_stream_ingestion.py tests/test_stream_runner.py tests/test_raw_page_staging.py tests/test_stream_execution.py tests/test_airflow_deployment.py
  git rm tests/test_scheduler_source_units.py
  git commit -m "refactor(automation): move stream runner out of scheduler"
  ```

### Task 3: Delete the scheduler namespace and stale deployment artifacts

**Files:**
- Create: `Dockerfile.viettelpay-mock`
- Create: `tests/test_legacy_scheduler_removed.py`
- Modify: `docker-compose.yml:223`
- Modify: `docker/README.md`
- Modify: `README.md`
- Modify: `pyproject.toml:69-77`
- Modify: `.github/workflows/ingestion-pipeline.yml:45-56`
- Modify: `tests/test_source_unit_orchestrator.py`
- Modify: `tests/test_source_unit_architecture.py`
- Modify: `docs/phase-2/sprint-2.5-airflow-migration.md`
- Modify: `docs/phase-2/sprint-2-incremental-recovery.md`
- Modify: `docs/phase-2/sprint-1-idempotency-report.md`
- Delete: `src/scheduler/__init__.py`
- Delete: `src/scheduler/jobs.py`
- Delete: `src/scheduler/source_unit_orchestrator.py`
- Delete: `Dockerfile`

**Interfaces:**
- Produces: no importable `src.scheduler` package and no executable legacy scheduler command.
- Produces: dedicated ViettelPay mock image with the same Compose command and port.
- Preserves: Airflow/API images and the `viettelpay-mock` service behavior.

- [ ] **Step 1: Write structural tests that fail while legacy artifacts exist.**

  ```python
  from pathlib import Path

  import yaml

  ROOT = Path(__file__).resolve().parents[1]


  def test_legacy_scheduler_namespace_and_command_are_removed():
      assert not (ROOT / "src" / "scheduler").exists()
      assert not (ROOT / "Dockerfile").exists()
      assert "--start-scheduler" not in (ROOT / "run.py").read_text()


  def test_viettelpay_mock_uses_dedicated_image():
      compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
      assert compose["services"]["viettelpay-mock"]["build"]["dockerfile"] == (
          "Dockerfile.viettelpay-mock"
      )
  ```

- [ ] **Step 2: Run the structural tests and verify they fail.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_legacy_scheduler_removed.py`

  Expected before implementation: both assertions fail.

- [ ] **Step 3: Remove compatibility imports and the dead package.**

  Update tests/scripts to import `process_source_units` and `run_source_stream` from `src.application`. Delete all three scheduler files only after this scan is empty:

  Run: `rtk proxy rg -n "src\.scheduler|daily_partner_fetch_job|run_fetch_config_once" src dags scripts tests`

- [ ] **Step 4: Replace the ambiguous root Dockerfile.**

  Create `Dockerfile.viettelpay-mock` from the existing Python image setup, expose port 8001, and use a valid default:

  ```dockerfile
  EXPOSE 8001
  CMD ["python", "-m", "scripts.demo.sprint2.mock_api", "--host", "0.0.0.0", "--port", "8001"]
  ```

  Point only `viettelpay-mock` at the new file and delete the root `Dockerfile` containing the invalid scheduler command.

- [ ] **Step 5: Update CI ownership and historical documentation.**

  Replace active `src/scheduler` quality/path filters with `src/application/automation`. Update current architecture references to the application runner; retain old names only in explicitly labeled historical sections.

- [ ] **Step 6: Remove the obsolete Mypy override.**

  Delete `src.scheduler.*` from `pyproject.toml`. Do not broaden another ignore list to hide errors introduced by the move.

- [ ] **Step 7: Verify imports, Compose, Docker build, and focused tests.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_legacy_scheduler_removed.py tests/test_airflow_deployment.py tests/test_stream_runner.py tests/test_source_unit_orchestrator.py tests/test_source_unit_architecture.py`

  Run: `docker compose config --quiet`

  Run: `docker compose build viettelpay-mock`

  Run: `rtk proxy rg -n "src\.scheduler|daily_partner_fetch_job|run_fetch_config_once|--start-scheduler" src dags scripts tests run.py docker-compose.yml Dockerfile* pyproject.toml .github`

  Expected: tests/build/config pass; active-code scan returns no matches.

- [ ] **Step 8: Commit scheduler removal.**

  ```bash
  git add Dockerfile.viettelpay-mock docker-compose.yml docker/README.md README.md pyproject.toml .github/workflows/ingestion-pipeline.yml docs tests src
  git rm Dockerfile src/scheduler/__init__.py src/scheduler/jobs.py src/scheduler/source_unit_orchestrator.py
  git commit -m "refactor(automation): remove legacy scheduler namespace"
  ```

---

## Phase B — Establish application ownership and thin APIs

### Task 4: Classify shared services into domain, core, and application modules

**Files:**
- Create: `src/domain/ingestion/retry_policy.py`
- Create: `src/domain/mapping/contract.py`
- Create: `src/core/business_day.py`
- Create: `src/application/runtime/__init__.py`
- Create: `src/application/runtime/service.py`
- Create: `src/application/audit/__init__.py`
- Create: `src/application/audit/service.py`
- Create: `src/application/automation/backfill_service.py`
- Create: `tests/test_application_service_boundaries.py`
- Modify: `src/infrastructure/runtime/repository.py`
- Modify: imports under `src/`, `dags/`, `scripts/`, and `tests/`
- Temporarily simplify to re-export facades: `src/services/retry_policy.py`, `mapping_contract.py`, `business_day.py`, `runtime_runs.py`, `audit.py`, `backfill_runs.py`

**Interfaces:**
- `RetryPolicy` and `RetryDisposition` move unchanged to `src.domain.ingestion.retry_policy`.
- Mapping canonicalization/validation functions move unchanged to `src.domain.mapping.contract`.
- `business_date`, `business_day_bounds`, and `utc_business_day_bounds` move unchanged to `src.core.business_day`.
- Runtime functions become `create_runtime_run`, `update_runtime_run`, and `serialize_partner_runtime_run` in `src.application.runtime.service`.
- Backfill API remains `BackfillRunService.start/resume_after_approval/get` with typed application exceptions that do not carry HTTP status codes.

- [ ] **Step 1: Add boundary tests before moving implementations.**

  ```python
  import inspect

  import src.application.automation.backfill_service as backfill_service
  import src.application.runtime.service as runtime_service
  import src.domain.ingestion.retry_policy as retry_policy


  def test_moved_services_do_not_depend_on_fastapi_or_api_modules():
      source = "\n".join(
          inspect.getsource(module)
          for module in (backfill_service, runtime_service, retry_policy)
      )
      assert "fastapi" not in source
      assert "src.api" not in source
  ```

- [ ] **Step 2: Run the boundary tests and verify imports fail.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_application_service_boundaries.py`

  Expected before implementation: new application/domain modules are missing.

- [ ] **Step 3: Move pure policies without wrappers in production callers.**

  Update `source_unit_orchestrator`, stream runner, API modules, and tests to import the domain/core targets directly. Keep old `src.services.*` files as one-line re-exports only until Task 5 removes the package.

- [ ] **Step 4: Move runtime persistence behind repository methods.**

  Add repository operations so application code no longer calls `.collection.update_one` directly:

  ```python
  async def update_fields(
      self,
      run_id: str,
      fields: dict[str, Any],
      *,
      attempt_event: dict[str, Any] | None = None,
  ) -> None:
      operation: dict[str, Any] = {"$set": fields}
      if attempt_event is not None:
          operation["$push"] = {"attemptHistory": attempt_event}
      await self.collection.update_one({"_id": run_id}, operation)
  ```

  Make `update_runtime_run()` call this method. Preserve `clear_finished_at`, orchestration serialization, and append-only attempt history.

- [ ] **Step 5: Move backfill orchestration and remove transport metadata from exceptions.**

  Keep distinct `BackfillRunValidationError`, `BackfillRunNotFoundError`, `BackfillRunConflictError`, and `BackfillRunUnavailableError`, but remove `status_code` attributes. Add explicit exception-to-status mapping in `src/api/automation.py`.

- [ ] **Step 6: Run focused domain/runtime/backfill tests.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_application_service_boundaries.py tests/test_runtime_architecture.py tests/test_backfill_runs.py tests/test_api_automation.py tests/test_source_unit_orchestrator.py`

  Run: `rtk proxy .venv/bin/ruff check src/domain/ingestion/retry_policy.py src/domain/mapping/contract.py src/core/business_day.py src/application/runtime src/application/audit src/application/automation/backfill_service.py`

- [ ] **Step 7: Commit the service classification.**

  ```bash
  git add src/domain src/core src/application src/infrastructure/runtime src/services tests dags scripts
  git commit -m "refactor(application): classify shared service responsibilities"
  ```

### Task 5: Move review and copilot workflows out of `src/services`

**Files:**
- Create: `src/application/review/__init__.py`
- Create: `src/application/review/errors.py`
- Create: `src/application/review/actions.py`
- Create: `src/application/review/reprocessing.py`
- Create: `src/application/review/runtime_validation.py`
- Create: `src/application/review/ai_mapping_context.py`
- Create: `src/application/review/evidence.py`
- Create: `src/application/review/raw_stream.py`
- Create: `src/application/copilot/__init__.py`
- Create: `src/application/copilot/context.py`
- Create: `src/infrastructure/mapping/composition.py`
- Create: `tests/test_review_application_boundaries.py`
- Modify: `src/api/review_packets.py`
- Modify: `src/api/copilot.py`
- Modify: `src/api/automation.py`
- Modify: `tests/test_api_review_packets.py`
- Modify: `tests/test_logical_reconciliation_batch.py`
- Modify: `tests/test_review_architecture.py`
- Delete: `src/services/`

**Interfaces:**
- Application functions accept `db`, domain models/IDs, actors, and injected ports; they never accept `Request`, `FastAPI`, or raise `HTTPException`.
- `build_config_loader(db) -> ConfigLoader` lives in infrastructure composition.
- Post-approval background scheduling uses an injected framework-neutral callback: `ScheduleBackground = Callable[[Awaitable[None]], None]`.
- API adapters map `ReviewNotFoundError`, `ReviewConflictError`, `ReviewValidationError`, and `ReviewUnavailableError` to 404/409/400/503.
- Existing response keys `postApproveRun`, `backfillRun`, `validationState`, `gate`, and packet serialization remain unchanged.

- [ ] **Step 1: Add tests that forbid framework imports in application workflows.**

  ```python
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]


  def test_review_application_has_no_fastapi_or_api_dependency():
      source = "\n".join(
          path.read_text()
          for path in (ROOT / "src" / "application" / "review").glob("*.py")
      )
      assert "from fastapi" not in source
      assert "src.api" not in source
      assert "HTTPException" not in source
      assert "Request" not in source
  ```

  Add behavior tests that call review actions with `db` and injected scheduler/gateway values instead of constructing FastAPI requests.

- [ ] **Step 2: Run the new tests and verify the package is missing.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_review_application_boundaries.py`

  Expected before implementation: application review modules are absent.

- [ ] **Step 3: Extract infrastructure composition and typed errors.**

  Move the config-loader builder to:

  ```python
  def build_config_loader(db: Any) -> ConfigLoader:
      return ConfigLoader(
          MappingConfigRepository(db),
          ConfigCache(),
          ConfigValidator(),
      )
  ```

  Define typed review exceptions in `errors.py`; only API adapters know HTTP status codes.

- [ ] **Step 4: Split review actions from reprocessing.**

  `actions.py` owns packet status/scope/approval decisions and starts a durable post-approval operation. `reprocessing.py` owns file/raw-page replay, ingestion, reconciliation, cache invalidation, and runtime/post-approval state transitions. Preserve the two existing paths:

  - local/file-level `reprocess_and_reconcile`
  - staged API page `_reprocess_staged_pages`

  Rename the private functions to public application operations only where routes/tests need them: `reprocess_file`, `reprocess_staged_pages`, and `start_post_approval_reprocess`.

- [ ] **Step 5: Move runtime validation and evidence readers as cohesive review queries.**

  Move code without changing gate/error payloads. `raw_stream.py` remains responsible for API/Airflow path translation and bounded page iteration; `runtime_validation.py` consumes that public iterator.

- [ ] **Step 6: Move copilot context and replace HTTP exceptions.**

  Use typed `CopilotContextValidationError` and `CopilotContextNotFoundError`; map them in `src/api/copilot.py`. Preserve context payloads and action keys.

- [ ] **Step 7: Adapt API routes and background task tracking.**

  The API creates tasks and passes this adapter into the application call:

  ```python
  def schedule_background(awaitable: Awaitable[None]) -> None:
      task = asyncio.create_task(awaitable)
      track_background_task(request.app, task)
  ```

  Application code receives only the callback, never `request.app`.

- [ ] **Step 8: Delete `src/services` after a complete import scan.**

  Run: `rtk proxy rg -n "from src\.services|import src\.services" src dags scripts tests`

  Expected before deletion: no matches. Then delete the temporary facades and remaining service files.

- [ ] **Step 9: Run review/copilot regressions.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_review_application_boundaries.py tests/test_api_review_packets.py tests/test_logical_reconciliation_batch.py tests/test_review_architecture.py tests/test_review_raw_stream.py tests/test_backfill_runs.py tests/test_api_automation.py`

  Run: `rtk proxy .venv/bin/ruff check src/application/review src/application/copilot src/infrastructure/mapping/composition.py src/api/review_packets.py src/api/copilot.py`

- [ ] **Step 10: Commit the review boundary.**

  ```bash
  git add src/application src/infrastructure/mapping src/api tests
  git rm -r src/services
  git commit -m "refactor(review): move workflows into application boundary"
  ```

### Task 6: Make automation routes thin adapters

**Files:**
- Create: `src/application/automation/job_queries.py`
- Create: `src/application/automation/job_commands.py`
- Create: `src/application/automation/job_contracts.py`
- Create: `tests/test_automation_job_services.py`
- Modify: `src/api/automation.py`
- Modify: `tests/test_api_automation.py`
- Modify: `tests/test_api_automation_run.py`
- Modify: `tests/test_api_automation_status.py`

**Interfaces:**
- `AutomationJobQueryService.list_jobs() -> list[dict[str, Any]]`
- `AutomationJobCommandService.run_now(command: RunAutomationJobCommand) -> dict[str, Any]`
- `AutomationJobCommandService.retry(command: RetryAutomationJobCommand) -> dict[str, Any]`
- `AutomationJobCommandService.resolve(command: ResolveAutomationRecoveryCommand) -> dict[str, Any]`
- Commands carry partner/actor/reason/action only; HTTP requests and status codes remain in API.
- Gateway/task-state/repository dependencies are injected through constructors.

- [ ] **Step 1: Add service tests for policy currently embedded in routes.**

  ```python
  @pytest.mark.asyncio
  async def test_run_now_rejects_partner_with_active_backfill():
      service = AutomationJobCommandService(
          fetch_repo=fetch_repo,
          backfill_repo=backfill_repo_with_active_run,
          runtime_repo=runtime_repo,
          checkpoint_repo=checkpoint_repo,
          workflow_gateway=workflow_gateway,
          runtime_service=runtime_service,
      )

      with pytest.raises(AutomationConflictError, match="Backfill is"):
          await service.run_now(
              RunAutomationJobCommand(partner="VNPAY", actor="operator")
          )
  ```

  Cover active runtime, retrying Airflow task, blocked checkpoint, waiting review, terminal failure, in-place retry, no-checkpoint fetch failure, and operator RETRY/SKIP resolution.

- [ ] **Step 2: Run service tests and verify the modules are missing.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_automation_job_services.py`

- [ ] **Step 3: Extract query projection without changing response shape.**

  Move the body of `list_automation_jobs` into `AutomationJobQueryService`. Keep `jobs`, `latestRuntimeRun`, `recentRuntimeRuns`, `recovery`, `activeBackfill`, duplicate fields, and messages byte-for-byte compatible where asserted.

- [ ] **Step 4: Extract run/retry/resolve policies and workflow submission.**

  Move `_airflow_task_state`, `_retry_existing_airflow_run`, `_queue_scheduler_run`, and checkpoint transition decisions into `job_commands.py`. Depend on the `WorkflowGateway` interface; do not instantiate Airflow adapters in application code.

- [ ] **Step 5: Reduce decorated route functions to transport adapters.**

  Each route follows this shape:

  ```python
  @router.post("/jobs/{partner}/run")
  async def run_automation_job_now(request: Request, partner: str):
      actor = require_actor(request, payload_field_name="actor")
      service = _job_command_service(request)
      try:
          return await service.run_now(
              RunAutomationJobCommand(partner=partner, actor=actor)
          )
      except AutomationApplicationError as exc:
          raise _automation_http_error(exc) from exc
  ```

- [ ] **Step 6: Add a route-structure regression test.**

  Parse `src/api/automation.py` with `ast` and assert each decorated route function has at most 12 top-level statements. Helpers for dependency composition and exception mapping are excluded; business policy is tested in the service.

- [ ] **Step 7: Run service and API tests.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_automation_job_services.py tests/test_api_automation.py tests/test_api_automation_run.py tests/test_api_automation_status.py tests/test_stream_execution.py tests/test_workflow_gateway.py`

  Run: `rtk proxy .venv/bin/ruff check src/application/automation/job_queries.py src/application/automation/job_commands.py src/application/automation/job_contracts.py src/api/automation.py tests/test_automation_job_services.py`

- [ ] **Step 8: Commit the automation API boundary.**

  ```bash
  git add src/application/automation src/api/automation.py tests/test_automation_job_services.py tests/test_api_automation.py tests/test_api_automation_run.py tests/test_api_automation_status.py
  git commit -m "refactor(api): delegate automation policy to application"
  ```

### Task 7: Move manual reconciliation execution out of the API

**Files:**
- Create: `src/application/reconciliation/manual_runs.py`
- Create: `src/application/reconciliation/queries.py`
- Create: `tests/test_manual_reconciliation_service.py`
- Modify: `src/application/reconciliation/__init__.py`
- Modify: `src/api/reconciliation.py:157-224`
- Modify: `src/api/reconciliation.py:491-643`
- Modify: `tests/test_api_reconciliation.py`

**Interfaces:**
- `QueueManualReconciliationCommand(partner: str, date: str, triggered_by: str)`
- `ManualReconciliationService.queue(command) -> PartnerRuntimeRun`
- `ManualReconciliationService.execute(run_id: str, context: ReconciliationRunContext) -> None`
- `ReconciliationContextQuery.resolve(partner: str, date: str) -> ReconciliationRunContext`
- The API owns background task creation; the application owns runtime transitions, reconciliation, and audit events.

- [ ] **Step 1: Add failing service tests for queue and terminal transitions.**

  ```python
  from unittest.mock import ANY

  import pytest


  @pytest.mark.asyncio
  async def test_execute_marks_runtime_completed_and_records_audit():
      await service.execute("run-1", context)

      runtime_service.update.assert_any_await(
          "run-1",
          status=PartnerRuntimeRunStatus.COMPLETED,
          reconciliation_count=3,
          finished_at=ANY,
      )
      audit_service.record.assert_awaited_once()
  ```

  Add the mirrored failure test with summarized error and `FAILED` audit metadata.

- [ ] **Step 2: Run the service tests and verify the module is absent.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_manual_reconciliation_service.py`

- [ ] **Step 3: Move latest-file/run context resolution into a query object.**

  Preserve source-file and mapping-version selection rules. Raise typed `ReconciliationContextUnavailableError` when no ingested partner rows exist.

- [ ] **Step 4: Move queue/execution state machine into application.**

  The application service creates the runtime, executes `ReconciliationService`, updates status, and records audit events. It does not call `asyncio.create_task` or inspect `request.app`.

- [ ] **Step 5: Adapt `/run` to schedule the application coroutine.**

  Validate actor/transport fields, call `queue`, then create and track `service.execute(...)`. Preserve the immediate response `{"ok": True, "run": ...}` and all existing status strings.

- [ ] **Step 6: Run reconciliation API and application tests.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_manual_reconciliation_service.py tests/test_api_reconciliation.py tests/test_reconciliation_architecture.py tests/test_reconciliation_run_architecture.py tests/test_runtime_architecture.py`

  Run: `rtk proxy .venv/bin/ruff check src/application/reconciliation src/api/reconciliation.py tests/test_manual_reconciliation_service.py`

- [ ] **Step 7: Commit the reconciliation boundary.**

  ```bash
  git add src/application/reconciliation src/api/reconciliation.py tests/test_manual_reconciliation_service.py tests/test_api_reconciliation.py
  git commit -m "refactor(reconciliation): move manual runs into application"
  ```

### Task 8: Move mapping and review business workflows out of route modules

**Files:**
- Create: `src/application/mapping/__init__.py`
- Create: `src/application/mapping/errors.py`
- Create: `src/application/mapping/service.py`
- Create: `src/application/mapping/proposals.py`
- Create: `src/application/review/mapping_workflow.py`
- Create: `src/application/review/scope_classification.py`
- Create: `tests/test_mapping_application_service.py`
- Create: `tests/test_review_mapping_workflow.py`
- Modify: `src/api/mappings.py`
- Modify: `src/api/review_packets.py`
- Modify: `tests/test_api_mappings.py`
- Modify: `tests/test_api_review_packets.py`

**Interfaces:**
- `MappingApplicationService.approve/reject/save` owns status transitions, versioning, cache invalidation, action synchronization, and audit.
- `MappingProposalService.create_from_source_file(command) -> MappingProposalResult` owns signature, AI generation, draft/action/packet creation, and scope metadata.
- `ReviewMappingWorkflow.generate/save/approve_keep_current/approve_activate` owns packet/mapping validation and calls Task 5 review actions.
- `ScopeClassificationService.classify(command) -> ScopeClassificationResult` owns LLM/rule-based scope decisions.
- Route modules retain Pydantic request models and serialization only.

- [ ] **Step 1: Add application tests for mapping state transitions.**

  Cover superseding the prior approved mapping, approving/rejecting a pending mapping, dynamic version allocation, audit actor propagation, cache invalidation failure tolerance, and proposal packet creation.

  ```python
  @pytest.mark.asyncio
  async def test_approve_supersedes_current_mapping_before_activating_draft():
      result = await service.approve(
          ApproveMappingCommand(config_id="draft-2", actor="reviewer")
      )

      assert result.status == MappingConfigStatus.APPROVED
      mapping_repo.mark_superseded.assert_awaited_once_with(
          "active-1", superseded_by="draft-2"
      )
  ```

- [ ] **Step 2: Add review workflow tests for AI mapping and scope classification.**

  Preserve missing-header/sample errors, canonical field mappings, validation-gate invalidation, approved/current mapping paths, and scope evidence fields.

- [ ] **Step 3: Run new tests and verify application modules are absent.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_mapping_application_service.py tests/test_review_mapping_workflow.py`

- [ ] **Step 4: Add repository methods for state transitions used by application services.**

  Replace route-level `.collection.update_one/replace_one/insert_one` calls with named repository methods such as `mark_superseded`, `approve`, `reject`, `replace_approved`, and `attach_draft`. Keep Mongo field aliases in infrastructure repositories.

- [ ] **Step 5: Move mapping proposal and approval workflows.**

  Move `_create_mapping_proposal_from_source_file` and approve/reject/save action bodies into application services. Keep file reading/signature and AI provider ports injectable for tests.

- [ ] **Step 6: Move review mapping and scope workflows.**

  Move `generate_ai_mapping_for_packet`, draft save logic, approve/keep-current orchestration, and `classify_scope_llm_for_packet`. Reuse Task 5 application review functions rather than calling API helpers.

- [ ] **Step 7: Reduce routes to validation, one service call, and error mapping.**

  Preserve all route paths, query/body aliases, response keys, and actor requirements. Do not change frontend types or behavior.

- [ ] **Step 8: Run mapping/review regressions and route-size checks.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_mapping_application_service.py tests/test_review_mapping_workflow.py tests/test_api_mappings.py tests/test_api_review_packets.py tests/test_review_architecture.py`

  Run: `rtk proxy .venv/bin/ruff check src/application/mapping src/application/review src/api/mappings.py src/api/review_packets.py`

  Expected: application tests own business behavior; endpoint tests prove transport compatibility.

- [ ] **Step 9: Commit the mapping/review API boundary.**

  ```bash
  git add src/application/mapping src/application/review src/api/mappings.py src/api/review_packets.py src/infrastructure tests
  git commit -m "refactor(api): move mapping and review workflows to application"
  ```

### Task 9: Move the remaining read/query business projections out of API modules

**Files:**
- Create: `src/application/operations/__init__.py`
- Create: `src/application/operations/queries.py`
- Create: `src/application/explorer/__init__.py`
- Create: `src/application/explorer/queries.py`
- Create: `src/application/insights/__init__.py`
- Create: `src/application/insights/queries.py`
- Create: `tests/test_api_query_boundaries.py`
- Modify: `src/api/operations.py`
- Modify: `src/api/data_explorer.py`
- Modify: `src/api/insights.py`
- Modify: `src/api/reconciliation.py:646-734`
- Modify: `tests/test_api_operations.py`
- Modify: `tests/test_api_data_explorer.py`
- Modify: `tests/test_api_insights.py`
- Modify: `tests/test_api_reconciliation.py`

**Interfaces:**
- `OperationsQueryService.partner_intake(query: PartnerIntakeQuery) -> dict[str, Any]`
- `OperationsQueryService.ingestion(query: IngestionOperationsQuery) -> dict[str, Any]`
- `DataExplorerQueryService.transactions/files/stats(...) -> dict[str, Any]`
- `InsightsQueryService.sample/sample_stats/summary/discrepancies/daily_report(...) -> Any`
- `InsightsQueryService.reconciliation_insights(query: ReconciliationInsightsQuery) -> Any`
- API modules retain `Query` declarations, validation of HTTP query syntax, response status mapping, and serialization only.

- [ ] **Step 1: Add route-boundary tests for the remaining large query handlers.**

  Parse the four route files with `ast`, find functions decorated with `router.get`, and assert each decorated handler has at most 12 top-level statements. Also forbid concrete repository and analysis-provider construction inside decorated functions:

  ```python
  import ast
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]
  ROUTE_FILES = (
      "operations.py",
      "data_explorer.py",
      "insights.py",
      "reconciliation.py",
  )


  def test_query_routes_are_transport_adapters():
      violations: list[str] = []
      for filename in ROUTE_FILES:
          path = ROOT / "src" / "api" / filename
          tree = ast.parse(path.read_text(), filename=str(path))
          for node in tree.body:
              if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                  continue
              is_get_route = any(
                  isinstance(decorator, ast.Call)
                  and isinstance(decorator.func, ast.Attribute)
                  and decorator.func.attr == "get"
                  for decorator in node.decorator_list
              )
              if is_get_route and len(node.body) > 12:
                  violations.append(f"{filename}:{node.name}:{len(node.body)}")
      assert violations == []
  ```

- [ ] **Step 2: Add application query tests that preserve current projections.**

  Move current endpoint assertions for pagination, filters, status totals, amount serialization, latest-file context, sample bounds, discrepancy focus mapping, and daily reports into service-level tests with injected repositories/providers. Keep endpoint tests for query aliases and HTTP errors.

- [ ] **Step 3: Run the boundary tests and verify current large routes fail.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_api_query_boundaries.py`

  Expected before implementation: at least `get_partner_intake` and one insight/explorer handler exceed the adapter limit.

- [ ] **Step 4: Extract operations and explorer projections.**

  Move repository reads, cross-collection aggregation, latest-file/run resolution, pagination metadata, status totals, and amount/date serialization into their application query services. Inject repositories or narrowly typed query ports; do not pass `Request` or raw FastAPI `Query` objects.

- [ ] **Step 5: Extract insight/report orchestration.**

  Move provider construction behind an injected `llm_provider_factory`, preserve the existing `summary/anomalies/patterns/recommendations` focus mapping, cache behavior, sample limits, and output field names. Reuse the same service for `/api/v1/insights/*` and reconciliation insights where their underlying use case is identical.

- [ ] **Step 6: Reduce route handlers to query construction and one service call.**

  Dependency helpers may compose concrete repositories/providers at module level. Decorated functions validate transport values, construct a typed query, await one application method, and map typed exceptions.

- [ ] **Step 7: Run query service and endpoint regressions.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_api_query_boundaries.py tests/test_api_operations.py tests/test_api_data_explorer.py tests/test_api_insights.py tests/test_api_reconciliation.py`

  Run: `rtk proxy .venv/bin/ruff check src/application/operations src/application/explorer src/application/insights src/api/operations.py src/api/data_explorer.py src/api/insights.py src/api/reconciliation.py`

- [ ] **Step 8: Commit the remaining API query boundaries.**

  ```bash
  git add src/application/operations src/application/explorer src/application/insights src/api/operations.py src/api/data_explorer.py src/api/insights.py src/api/reconciliation.py tests
  git commit -m "refactor(api): move query projections to application"
  ```

---

## Phase C — Enforce script boundaries and verify the system

### Task 10: Convert scripts into adapters over public production use cases

**Files:**
- Create: `tests/test_script_boundaries.py`
- Create: `tests/test_benchmark_script_contracts.py`
- Modify: `scripts/demo/sprint2/evaluation.py`
- Modify: `scripts/demo/sprint2/seed_vnpay_filedrop_backfill.py`
- Modify: `scripts/reproducible_benchmark.py`
- Modify: `scripts/parallel_benchmark.py`
- Modify: `scripts/benchmark_reconcile_million.py`
- Modify: `scripts/demo/scenarios/seed_zalopay_ai_test.py`
- Modify: `scripts/demo/README.md`
- Modify: `README.md`

**Interfaces:**
- Recovery evaluation imports `process_source_units` and `units_after_checkpoint` from public application modules.
- Ingestion benchmarks call `IngestionPipeline.execute(ProcessFileCommand(...))`, not `process_file()` argument wrappers.
- Reconciliation benchmarks call `ReconciliationService.execute(ReconciliationCommand(...))` from the production composition root, not `ReconciliationEngine.reconcile()` directly.
- VNPAY backfill fixture calls `BackfillRunService.start()`; its injected pending-packet finder may create fixture evidence, but the script does not construct a `BackfillRun` state machine.
- Data generators may construct rows/files and call repositories; they may not import private names from `src.*`.

- [ ] **Step 1: Add AST-based script boundary tests.**

  ```python
  import ast
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]


  def test_scripts_do_not_import_scheduler_private_or_engine_modules():
      violations = []
      for path in (ROOT / "scripts").rglob("*.py"):
          tree = ast.parse(path.read_text(), filename=str(path))
          for node in ast.walk(tree):
              if isinstance(node, ast.ImportFrom) and node.module:
                  if node.module.startswith("src.scheduler"):
                      violations.append(f"{path}:{node.lineno}:{node.module}")
                  if node.module == "src.reconciliation.engine":
                      violations.append(f"{path}:{node.lineno}:{node.module}")
                  if node.module.startswith("src.") and any(
                      alias.name.startswith("_") for alias in node.names
                  ):
                      violations.append(f"{path}:{node.lineno}:private import")
      assert violations == []
  ```

- [ ] **Step 2: Run the boundary test and capture current violations.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_script_boundaries.py`

  Expected before implementation: violations include Sprint 2 evaluation, private seed helpers, and direct reconciliation engine imports.

- [ ] **Step 3: Update recovery evaluation and demo instructions.**

  Replace scheduler/private imports and change the ZaloPay instruction to trigger the Airflow-backed Run Now application endpoint; remove references to `daily_partner_fetch_job()`.

- [ ] **Step 4: Make VNPAY backfill setup use the production backfill service.**

  Seed only source files, internal rows, fetch config, and draft mapping. Instantiate `BackfillRunService` with repositories and a no-submit gateway; let `start()` create the parent/day records. Supply a `pending_review_packet_finder(partner, run_id)` fixture adapter that creates and returns the deterministic packet ID.

- [ ] **Step 5: Make benchmarks use public commands.**

  Replace ingestion wrapper calls with:

  ```python
  result = await pipeline.execute(
      ProcessFileCommand(
          file_path=str(path),
          partner=PARTNER,
          workflow_type="UPC",
          file_type=FileType.SETTLEMENT,
          reconciliation_date=day,
          config_version=config.config_version,
      )
  )
  ```

  Replace direct engine calls with `build_reconciliation_service(...).execute(ReconciliationCommand(...))`. Move reusable seed helpers that begin with `_` behind public fixture functions before importing them across script modules.

- [ ] **Step 6: Document the fixture exception explicitly.**

  In `scripts/demo/README.md`, state that seed/reset scripts may write deterministic fixture data through repositories, but all runtime state transitions must go through application services. List the production application entrypoint used by each demo/benchmark.

- [ ] **Step 7: Run script tests and dry-run entrypoints.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_script_boundaries.py tests/test_benchmark_script_contracts.py tests/test_vnpay_filedrop_backfill_demo.py tests/test_viettelpay_sprint2_demo.py tests/test_sprint2_ui_demo.py`

  Run: `rtk proxy .venv/bin/python -m scripts.demo.sprint2.run --help`

  Run: `rtk proxy .venv/bin/python -m scripts.demo.sprint2.seed_vnpay_filedrop_backfill --help`

  Expected: tests pass and help commands perform no database mutation.

- [ ] **Step 8: Commit script boundary cleanup.**

  ```bash
  git add scripts tests/test_script_boundaries.py tests/test_vnpay_filedrop_backfill_demo.py README.md
  git commit -m "refactor(scripts): call public application use cases"
  ```

### Task 11: Final architectural and behavioral verification

**Files:**
- Modify: `docs/phase-2/sprint-2.5-airflow-migration.md`
- Modify: `docs/phase-2/sprint-2.6-recovery-hardening.md`
- Modify: `docs/CI-MAP.md`
- Modify: `README.md`
- Refresh: `.codegraph/codegraph.db` (Git-ignored)

**Interfaces:**
- Produces: verified Airflow-only control plane, application-owned use cases, thin route adapters, script boundary enforcement, current documentation, and refreshed dependency index.

- [ ] **Step 1: Run final forbidden-dependency scans.**

  Run: `rtk proxy rg -n "src\.scheduler|daily_partner_fetch_job|run_fetch_config_once|--start-scheduler|from src\.services|import src\.services" src dags scripts tests run.py Dockerfile* docker-compose.yml pyproject.toml .github`

  Expected: no active-code matches.

  Run: `rtk proxy rg -n "from fastapi|src\.api|HTTPException|Request" src/application src/domain`

  Expected: no matches.

- [ ] **Step 2: Run focused backend suites by boundary.**

  Run: `rtk proxy .venv/bin/pytest -q tests/test_stream_identity.py tests/test_stream_ingestion.py tests/test_stream_runner.py tests/test_stream_execution.py tests/test_raw_page_staging.py tests/test_airflow_deployment.py tests/test_airflow_backfill.py`

  Run: `rtk proxy .venv/bin/pytest -q tests/test_automation_job_services.py tests/test_manual_reconciliation_service.py tests/test_mapping_application_service.py tests/test_review_mapping_workflow.py tests/test_review_application_boundaries.py tests/test_api_query_boundaries.py tests/test_script_boundaries.py tests/test_benchmark_script_contracts.py`

  Run: `rtk proxy .venv/bin/pytest -q tests/test_api_automation.py tests/test_api_automation_run.py tests/test_api_reconciliation.py tests/test_api_mappings.py tests/test_api_review_packets.py`

  Expected: all focused suites pass.

- [ ] **Step 3: Run complete backend quality gates.**

  Run: `rtk proxy .venv/bin/pytest -q`

  Run: `rtk proxy .venv/bin/ruff check src dags scripts cli tests`

  Run: `rtk proxy .venv/bin/mypy src --show-error-codes`

  Run: `git diff --check`

  Expected: all commands exit 0. Existing explicitly marked integration/LLM skips remain skips; no test is removed or newly xfailed to obtain a pass.

- [ ] **Step 4: Validate deployment artifacts.**

  Run: `docker compose config --quiet`

  Run: `docker compose build api airflow-api-server airflow-scheduler airflow-dag-processor viettelpay-mock`

  Confirm the resolved Compose service set has no legacy `scheduler`, API uses `Dockerfile.api`, Airflow uses `Dockerfile.airflow`, and the mock uses `Dockerfile.viettelpay-mock`.

- [ ] **Step 5: Refresh and inspect CodeGraph after structural moves.**

  Run: `rtk codegraph sync`

  Run: `rtk codegraph status`

  Run: `rtk codegraph callers execute_stream`

  Run: `rtk codegraph callers run_source_stream`

  Expected: index is complete/up to date; Airflow/DAG calls `execute_stream`, `execute_stream` reaches `run_source_stream`, and no node path begins with `src/scheduler/` or `src/services/`.

- [ ] **Step 6: Update current-state documentation with measured evidence.**

  Record test counts, quality-gate results, Compose build result, CodeGraph status, and final ownership:

  ```text
  Airflow DAG -> execute_stream -> run_source_stream
      -> fetcher -> raw staging/checkpoint -> ingestion command
      -> reconciliation service -> runtime/review outcome
  ```

  Keep historical scheduler names only where the document explicitly describes the pre-refactor implementation.

- [ ] **Step 7: Review the diff and commit verification/docs.**

  Run: `rtk proxy git status --short`

  Run: `rtk proxy git diff --stat`

  Run: `git diff --check`

  ```bash
  git add README.md docs .github pyproject.toml Dockerfile* docker-compose.yml
  git commit -m "docs(architecture): record application boundary cutover"
  ```

## Done when

- [ ] `src/scheduler/` and `src/services/` no longer exist.
- [ ] Airflow reaches the production stream runner only through `src.application.automation`.
- [ ] `daily_partner_fetch_job`, `run_fetch_config_once`, scheduler private helpers, and `--start-scheduler` have no active references.
- [ ] Stream identity, retry/replay, raw staging, waiting review, safe duplicate, and backfill isolation tests pass unchanged in meaning.
- [ ] Application/domain code has no FastAPI/API dependency.
- [ ] Automation, reconciliation, mapping, review, operations, explorer, and insight routes delegate business workflows and projections to application services.
- [ ] Scripts have no scheduler, private application, or direct reconciliation-engine imports.
- [ ] Frontend files are untouched and all existing API response contracts remain compatible.
- [ ] Full pytest, Ruff, Mypy, Compose validation/build, diff check, and CodeGraph status pass.
