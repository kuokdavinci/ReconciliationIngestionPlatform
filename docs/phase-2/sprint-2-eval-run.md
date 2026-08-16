# Sprint 2 Incremental Recovery Evaluation

- Evidence type: `deterministic in-memory mock; no production database mutation`
- Generated at: `2026-08-05T02:15:17.341046+00:00`
- Summary: `4/4 passed`, `0 failed`

| Scenario | Expected | Actual | Passed | Duration (ms) |
|---|---|---|---:|---:|
| S2-02 — Failure giữa page 2 | page 1 completed và stream dừng tại page 2 | processed=1, stoppedAt=page:2 | True | 0.116 |
| S2-03 — Restart và resume | chạy tiếp từ page 2, sau đó page 3 | processed=2, units=['page:2', 'page:3'] | True | 0.023 |
| S2-05 — Cursor/page replay | unit đã completed không ingest lần hai | replayed=1 | True | 0.006 |
| S2-13 — Data invariant | không có duplicate ingestion key sau recovery | ingestedKeys=['page:1', 'page:2', 'page:3'], duplicateCount=0 | True | 0.001 |

## Final checkpoint

- Status: `DISCOVERED`
- Last completed unit: `page:3`
- Cursor after: `None`
- Duplicate ingestion keys: `0`

## Operator recovery UI demo

Playwright chạy độc lập với backend bằng deterministic API mock:

1. `/schedules` hiển thị ViettelPay `Recovery: FAILED`, `page:1` đã checkpoint,
   `page:2` lỗi `fetch_timeout`, `page:3` ở trạng thái `PENDING`.
2. Operator mở `View recovery`, kiểm tra timeline và bấm `Retry now`.
3. UI nhận trạng thái `PROCESSING`, sau đó refresh bounded chuyển sang
   `COMPLETED`, checkpoint cuối `page:3` và `Duplicate count: 0`.
4. `Escape` đóng side panel; replay được biểu diễn là `REPLAYED`, không phải
   failure.

Scenario: `frontend-next/e2e/dashboard-interactions.spec.ts` — `1 passed`.

## VNPAY FileDrop ordered backfill coverage

The operator path is now covered separately from the historical ViettelPay API
evaluation:

1. `make vnpay-backfill-reset` clears prior VNPAY partner/result rows, then
   creates deterministic business-date files, matching PostgreSQL internal
   rows, an enabled FileDrop config, a draft mapping, and a pending review
   packet with bounded internal evidence.
2. Schedules starts one parent backfill and displays each business date in the
   progress panel.
3. The parent remains `WAITING_CONFIG` until Guided Review approves the draft
   mapping. Approval resumes the same Airflow backfill run rather than queuing
   an unrelated post-approval replay.
4. Backend tests verify date expansion, ordered execution, first-failure stop,
   scheduled-checkpoint isolation, and parent resumption after approval.
5. The live Docker acceptance path should finish `COMPLETED` for every business
   day and produce three `MATCHED` results per seeded day.

This is deterministic code/UI evidence. It does not replace the live Docker
acceptance run against MongoDB, PostgreSQL, Airflow, and the mounted
`mock_data/` directory.

## Current repository verification — 2026-08-14

This section supersedes the older verification snapshot above when assessing
the current branch. It records what was actually re-run locally; it does not
promote mock or unit evidence to live business acceptance.

### Automated evidence

- Codegraph: `448` indexed files, `6,738` nodes, `17,221` edges; status is up
  to date.
- Sprint 2/2.5 focused regression set: `190 passed` across checkpoint,
  pagination, FileDrop/SFTP, stream orchestration, Airflow, review and
  backfill contracts.
- Workflow-equivalent ingestion CI command: `52 passed, 1 skipped` across the
  collected `53` tests. The skipped case is the environment-gated Sprint 1
  benchmark scenario.
- Backend-quality selection excluding the two ingestion workflows: `1,116
  passed, 8 skipped` when PostgreSQL integration cases are excluded. The two
  PostgreSQL integration tests are still environment-gated locally because the
  sandbox cannot complete the `localhost:5432` asyncpg probe; GitHub Actions
  provides the declared PostgreSQL service for these cases.
- Sprint 1 index/benchmark checks: `10 passed`.
- Ruff: passed for `src`, `dags`, `scripts` and `cli`; ingestion-specific Ruff
  scope also passed.
- Mypy: passed for `207` source files.
- Frontend production interaction suite: `7 passed` after making the optional
  external icon font non-blocking for Playwright.

### Compose pilot evidence

- API image/container: `sha256:cb2c9e4197efd6c1b925f510b3cfe43d604f07814285d3811fa5a15887214d13`.
- API container is running and `/openapi.json` returns HTTP 200.
- Airflow metadata database, scheduler and DAG processor report healthy.
- Airflow DAG import errors report `No data found`.
- Runtime configuration is `APP_AUTOMATION_ORCHESTRATOR=airflow`,
  `AIRFLOW_GLOBAL_SCHEDULE=none` and `AIRFLOW_TASK_RETRIES=0`.
- No legacy `reconciliation-scheduler` container is running.

### Evidence still not accepted as final DoD

The exact 53-test ingestion workflow invocation now completes cleanly with
`52 passed, 1 skipped` in `0.66s` under the local CI-equivalent environment.
The earlier stall was caused by mocked ingestion tests reaching the real
PostgreSQL scope classifier and by file hashing using the constrained default
executor; tests now isolate the scope query and the hash path is deterministic
for the ingestion boundary.

The live business scenarios remain partial: multi-fingerprint FileDrop/SFTP
retention and recovery, the full bounded Airflow/application retry and state
matrix, scheduled-checkpoint isolation during a real scheduled-plus-backfill
run, and per-partner rollback. The current-image VNPAY smoke run is recorded
in the Sprint 2.5 evidence matrix.
