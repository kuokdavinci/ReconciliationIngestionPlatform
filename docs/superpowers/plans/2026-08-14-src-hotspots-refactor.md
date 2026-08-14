# Source Hotspots Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tách các hàm phình to và gom ownership/helper bị lặp trong `src/` mà không thay đổi API, schema hoặc semantics ingestion/review/reconciliation.

**Architecture:** API giữ transport-only; scope/proposal/reprocessing thuộc application. Reconciliation và stream runner giữ public entry point nhưng delegate sang executor/runner nhỏ, nhận dependency rõ ràng. Các adapter reader/repository vẫn giữ interface lặp có chủ ý.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest/pytest-asyncio, Ruff, mypy, MongoDB/Motor, PostgreSQL/SQLAlchemy.

## Global Constraints

- Không sửa hoặc stage `TODO.md`, `docs/phase-2/sprint-1-eval-benchmark-run.md`, hoặc hai plan untracked có sẵn trong worktree.
- Không xoá `domain`/`infrastructure`, không đổi database schema và không đổi API response shape.
- Không dùng nhận diện `AsyncMock`, `MagicMock` hoặc `unittest.mock` để chọn production backend.
- Mọi production code mới phải có test đỏ trước, test xanh sau; test phải kiểm tra behavior, không chỉ kiểm tra mock call count.
- Mỗi task phải chạy test hẹp trước khi chuyển task; cuối plan chạy Ruff, mypy `src/`, backend CI suite, ingestion suite và codegraph status.
- Mọi lệnh shell dùng trong workspace phải chạy qua RTK (`rtk ...`).

---

### Task 1: Canonical API and review-scope helpers

**Files:**
- Create: `src/api/dependencies.py`
- Create: `src/api/query_validation.py`
- Create: `src/application/review/scope_support.py`
- Modify: `src/api/audit.py`, `src/api/automation.py`, `src/api/copilot.py`, `src/api/data_explorer.py`, `src/api/insights.py`, `src/api/mappings.py`, `src/api/operations.py`, `src/api/reconciliation.py`, `src/api/review_packets.py`
- Modify: `src/application/review/scope_classification.py`
- Test: `tests/test_api_query_helpers.py`, `tests/test_scope.py`, `tests/test_api_review_packets.py`, `tests/test_review_application_boundaries.py`

**Interfaces:**
- `src/api/dependencies.py` exports `get_request_db(request: Request) -> Any` and preserves the current 503 error detail.
- `src/api/query_validation.py` exports `validate_date(value: str | None) -> str` and `validate_partner(value: str | None, *, required: bool = False) -> str | None`.
- `src/application/review/scope_support.py` owns `_scope_probabilities`, `_normalize_scope_probabilities`, `_apply_scope_guardrails`, `_column_index`, `_scope_mapping_columns`, and `_extract_scope_keys` behavior.
- `src/api/review_packets.py` calls application scope support instead of defining business rules locally.

- [ ] **Step 1: Add failing tests for shared API helper behavior.** Assert missing/invalid dates return HTTP 400, optional blank partner is rejected, required partner is trimmed, and missing request DB returns HTTP 503 with the existing detail.
- [ ] **Step 2: Run the focused tests and verify they fail because the shared modules do not exist.**

Run: `rtk proxy .venv/bin/pytest -q tests/test_api_query_helpers.py`

Expected: FAIL with import errors for the new helper modules.

- [ ] **Step 3: Implement the shared dependency and validation helpers, then update API imports without changing route signatures.**
- [ ] **Step 4: Add failing scope-support tests for numeric/Excel column conversion, probability normalization, and key extraction from list/dict rows.**
- [ ] **Step 5: Run the scope tests and verify the failure is caused by the missing canonical scope module.**
- [ ] **Step 6: Move the duplicated scope behavior into `scope_support.py`, make `scope_classification.py` import it, and remove the duplicate private implementations from `review_packets.py`.**
- [ ] **Step 7: Run `rtk proxy .venv/bin/pytest -q tests/test_api_query_helpers.py tests/test_scope.py tests/test_api_review_packets.py tests/test_review_application_boundaries.py` and commit the task.**

### Task 2: Canonical business-date and file-identity helpers

**Files:**
- Create: `src/core/file_identity.py`
- Modify: `src/application/automation/airflow_runtime.py`, `src/core/business_day.py`, `src/fetchers/base.py`, `src/pipeline/file_claim.py`
- Test: `tests/test_airflow_runtime.py`, `tests/test_ingestion_components.py`, `tests/test_ingestion_pipeline.py`

**Interfaces:**
- `src/core/business_day.py::business_date` is the canonical configured-timezone conversion.
- `src/core/file_identity.py::compute_file_hash(file_path: str) -> str` is the canonical synchronous SHA-256 implementation.
- Async claim code delegates hashing through `asyncio.to_thread`; Airflow uses `src.core.business_day.business_date` rather than a second timezone constant.

- [ ] **Step 1: Add failing tests proving Airflow date resolution and file claim hashing use the canonical helpers for naive/aware datetimes and identical file bytes.**
- [ ] **Step 2: Run the focused tests and verify the failure demonstrates the current duplicate timezone/hash paths.**
- [ ] **Step 3: Implement the canonical file hash helper and delegate both fetcher and claim code to it.**
- [ ] **Step 4: Replace the Airflow-local `business_date` implementation with the configured core helper while preserving the existing `resolve_reconciliation_date` behavior.**
- [ ] **Step 5: Run the focused tests plus existing Airflow/ingestion tests and commit the task.**

### Task 3: Explicit reconciliation execution backends

**Files:**
- Create: `src/reconciliation/document_executor.py`
- Create: `src/reconciliation/postgres_executor.py`
- Modify: `src/reconciliation/engine.py`
- Modify: `src/infrastructure/reconciliation/composition.py`, `src/domain/reconciliation/ports.py` if an explicit backend capability is needed
- Test: `tests/test_reconciliation.py`, `tests/test_reconciliation_architecture.py`, `tests/test_reconciliation_run_architecture.py`

**Interfaces:**
- `ReconciliationEngine.reconcile(...)` remains the public entry point.
- The engine selects an executor from an explicit `backend`/capability supplied by composition or repository adapter, never by inspecting mock types.
- `PostgresReconciliationExecutor` owns the SQL transaction/query path; `DocumentReconciliationExecutor` owns the document-store compatibility path used by isolated tests/legacy adapters.

- [ ] **Step 1: Add a regression test that injects an explicit document backend and proves it does not depend on `unittest.mock` type detection.**
- [ ] **Step 2: Run the regression test against the current implementation and verify it fails because no explicit backend contract exists.**
- [ ] **Step 3: Extract the current PostgreSQL branch into `PostgresReconciliationExecutor` without changing SQL parameters, deletion scope, result mapping, or write batching.**
- [ ] **Step 4: Extract the current document-store branch into `DocumentReconciliationExecutor` without changing matching, scope, or result status behavior.**
- [ ] **Step 5: Make composition inject the production PostgreSQL executor and update direct test construction to request the document executor explicitly.**
- [ ] **Step 6: Remove `AsyncMock`/`MagicMock` backend selection and run reconciliation architecture/unit tests.**
- [ ] **Step 7: Commit the task only after `tests/test_reconciliation.py tests/test_reconciliation_architecture.py tests/test_reconciliation_run_architecture.py` pass.**

### Task 4: Split source stream execution

**Files:**
- Create: `src/application/automation/stream_lifecycle.py`
- Create: `src/application/automation/paginated_stream_runner.py`
- Create: `src/application/automation/file_stream_runner.py`
- Create: `src/application/automation/stream_failure.py`
- Modify: `src/application/automation/stream_runner.py`
- Test: `tests/test_stream_runner.py`, `tests/test_stream_execution.py`, `tests/test_stream_ingestion.py`, `tests/test_ingestion_checkpoint.py`

**Interfaces:**
- `run_source_stream(...) -> dict[str, Any]` remains the public dispatcher.
- Lifecycle helpers own create/update/finalize runtime calls.
- Paginated runner owns fetch/page checkpoint/staging/review-gate flow.
- File runner owns non-paginated file/SFTP flow.
- Failure helper preserves the current retryable/error-code/result payloads.

- [ ] **Step 1: Add focused tests for dispatcher selection and preservation of blocked/already-completed checkpoint results.**
- [ ] **Step 2: Run the focused tests and confirm the new runner interfaces are absent.**
- [ ] **Step 3: Extract runtime lifecycle and failure payload construction without changing returned dictionaries.**
- [ ] **Step 4: Extract paginated API processing, including checkpoint updates, raw staging and review-gate handling.**
- [ ] **Step 5: Extract file/SFTP processing and leave `run_source_stream` as the mode dispatcher.**
- [ ] **Step 6: Run all stream/ingestion tests and verify the public result payloads and checkpoint transitions.**
- [ ] **Step 7: Commit the task.**

### Task 5: Consolidate review proposal ownership and reprocessing

**Files:**
- Create: `src/application/review/proposal_creation.py`
- Create: `src/application/review/staged_page_replay.py`
- Create: `src/application/review/post_approval_reconciliation.py`
- Modify: `src/config/config_health.py`, `src/application/mapping/proposals.py`, `src/application/automation/stream_review_gate.py`, `src/application/review/reprocessing.py`, and affected callers/tests
- Test: `tests/test_review_mapping_workflow.py`, `tests/test_review_application_boundaries.py`, `tests/test_review_raw_stream.py`, `tests/test_stream_runner.py`, `tests/test_api_review_packets.py`

**Interfaces:**
- `config_health` exposes health/decision functions and delegates review artifact creation to application review.
- `MappingProposalService` and scheduled stream proposal creation share one application-owned proposal/packet builder while retaining source-specific metadata.
- `reprocessing.py` remains the public facade; page replay and post-approval reconciliation are internal application services.

- [ ] **Step 1: Add architecture tests that fail if `config_health` directly constructs `ReviewPacket`/`CopilotAction` or if reprocessing owns both page replay and final reconciliation lifecycle.**
- [ ] **Step 2: Run those tests and verify the failure reflects the current ownership.**
- [ ] **Step 3: Extract shared proposal/action/packet construction into `proposal_creation.py` and preserve idempotent pending-proposal reuse.**
- [ ] **Step 4: Make `config_health` delegate to the new application service and retain compatibility wrappers only where existing callers require them.**
- [ ] **Step 5: Extract staged page materialization/aggregation into `staged_page_replay.py`.**
- [ ] **Step 6: Extract post-approval run lifecycle and reconciliation finalization into `post_approval_reconciliation.py`, leaving `reprocessing.py` as a facade.**
- [ ] **Step 7: Run the review, stream, and API review tests and commit the task.**

### Task 6: Whole-branch verification and structural cleanup

**Files:**
- Modify only files required by failing verification or architecture assertions.
- Do not modify unrelated dirty files listed in Global Constraints.

- [ ] **Step 1: Run `rtk git diff --check` and inspect the complete diff.**
- [ ] **Step 2: Run Ruff on `src/` and tests, then mypy on `src/`.**
- [ ] **Step 3: Run the backend exact CI suite and the ingestion suite.**
- [ ] **Step 4: Refresh the codegraph using the repository's configured tooling and run `rtk codegraph status`.**
- [ ] **Step 5: Verify oversized public functions have been reduced and no forbidden mock-based backend selection remains.**
- [ ] **Step 6: Record final status, changed files, tests, and any deferred persistence namespace migration.**
