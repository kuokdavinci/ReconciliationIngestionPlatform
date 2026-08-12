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
