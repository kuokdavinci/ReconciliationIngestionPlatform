# Đánh giá Sprint 2 — Incremental Recovery

- Loại evidence: `deterministic in-memory mock; no production database mutation`
- Thời điểm sinh: `2026-08-05T02:15:17.341046+00:00`
- Tóm tắt: `4/4 passed`, `0 failed`

| Scenario | Kỳ vọng | Thực tế | Passed | Duration (ms) |
|---|---|---|---:|---:|
| S2-02 — Failure giữa page 2 | page 1 completed và stream dừng tại page 2 | processed=1, stoppedAt=page:2 | True | 0.116 |
| S2-03 — Restart và resume | chạy tiếp từ page 2, sau đó page 3 | processed=2, units=['page:2', 'page:3'] | True | 0.023 |
| S2-05 — Cursor/page replay | unit đã completed không ingest lần hai | replayed=1 | True | 0.006 |
| S2-13 — Data invariant | không có duplicate ingestion key sau recovery | ingestedKeys=['page:1', 'page:2', 'page:3'], duplicateCount=0 | True | 0.001 |

## Checkpoint cuối

- Status: `DISCOVERED`
- Unit hoàn tất cuối: `page:3`
- Cursor sau cùng: `None`
- Ingestion key duplicate: `0`

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

Operator path hiện được kiểm tra riêng với historical ViettelPay API
evaluation:

1. `make vnpay-backfill-reset` xóa partner/result row VNPAY cũ, sau đó tạo file
   theo business date, internal row khớp trong PostgreSQL, FileDrop config đã
   enable, draft mapping và pending review packet có bounded internal evidence.
   Nếu không đặt `VNPAY_BACKFILL_FROM` và `VNPAY_BACKFILL_TO`, fixture dùng bốn
   business day gần nhất; environment variable có thể thu hẹp focused smoke run.
2. Schedules start một parent backfill và hiển thị từng business date trong progress panel.
3. Parent giữ `WAITING_CONFIG` tới khi Guided Review approve draft mapping. Approval
   resume cùng Airflow backfill run thay vì queue post-approval replay không liên quan.
4. Backend test kiểm tra date expansion, ordered execution, first-failure stop,
   scheduled-checkpoint isolation và parent resumption sau approval.
5. Live Docker acceptance path cần kết thúc `COMPLETED` cho mọi business day đã seed
   và tạo ba `MATCHED` result cho mỗi ngày.

Đây là deterministic code/UI evidence, không thay thế live Docker acceptance run
với MongoDB, PostgreSQL, Airflow và thư mục `mock_data/` được mount.

## Kiểm chứng repository hiện tại — 2026-08-14

Phần này thay thế verification snapshot cũ khi đánh giá branch hiện tại. Nội
dung ghi lại những gì đã chạy lại local; không nâng mock/unit evidence thành
live business acceptance.

### Automated evidence

- Codegraph: `448` indexed files, `6,738` nodes, `17,221` edges; status is up
  to date.
- Sprint 2/2.5 focused regression set: `190 passed` across checkpoint,
  pagination, FileDrop/SFTP, stream orchestration, Airflow, review and
  backfill contracts.
- Ingestion CI command tương đương workflow: `52 passed, 1 skipped` trên tổng
  `53` test đã thu thập. Case bị skip là Sprint 1 benchmark scenario có
  environment gate.
- Backend-quality selection, loại hai ingestion workflow: `1,116 passed, 8
  skipped` khi loại PostgreSQL integration case. Hai PostgreSQL integration test
  vẫn có environment gate local vì sandbox không hoàn tất asyncpg probe tới
  `localhost:5432`; GitHub Actions cung cấp PostgreSQL service đã khai báo.
- Sprint 1 index/benchmark checks: `10 passed`.
- Ruff: passed for `src`, `dags`, `scripts` and `cli`; ingestion-specific Ruff
  scope also passed.
- Mypy: passed for `207` source files.
- Frontend production interaction suite: `7 passed` sau khi làm external icon
  font tùy chọn không block Playwright.

### Compose pilot evidence

- API image/container: `sha256:cb2c9e4197efd6c1b925f510b3cfe43d604f07814285d3811fa5a15887214d13`.
- API container is running and `/openapi.json` returns HTTP 200.
- Airflow metadata database, scheduler and DAG processor report healthy.
- Airflow DAG import errors report `No data found`.
- Runtime configuration is `APP_AUTOMATION_ORCHESTRATOR=airflow`,
  `AIRFLOW_GLOBAL_SCHEDULE=none` and `AIRFLOW_TASK_RETRIES=0`.
- No legacy `reconciliation-scheduler` container is running.

### Evidence chưa được chấp nhận là DoD cuối cùng

Lệnh ingestion workflow gồm đúng 53 test hiện hoàn tất sạch với `52 passed, 1
skipped` trong `0.66s` ở môi trường tương đương CI local. Lần stall trước do
mocked ingestion test chạm PostgreSQL scope classifier thật và file hashing dùng
constrained default executor; test hiện cô lập scope query và hash path
deterministic ở ingestion boundary.

Live business scenario vẫn partial: retention/recovery nhiều fingerprint cho
FileDrop/SFTP, đầy đủ Airflow/application retry và state matrix có giới hạn,
scheduled-checkpoint isolation trong scheduled-plus-backfill run thật và
rollback theo partner. Current-image VNPAY smoke run được ghi trong Sprint 2.5
evidence matrix.
