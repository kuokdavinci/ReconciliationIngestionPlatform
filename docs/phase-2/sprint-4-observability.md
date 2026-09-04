# Sprint 4 — Observability cho ingestion runtime

**Trạng thái:** `closed — no candidate promoted`

Sprint 4 đã chốt lớp observability cuối cùng trên Schedules. Runtime giữ
nguyên counter, duplicate, checkpoint và ingestion semantics; chỉ bổ sung
telemetry, persisted summary và cách hiển thị trạng thái.

## Kết quả

| Hạng mục | Kết quả |
|---|---|
| Runtime summary | Persist `stageSummary` với counter, stage, quality, checkpoint và `batchMetrics`; có thêm `parseRowsMs`, `normalizeMs`, `validateMs`. |
| Observability write | Lỗi ghi summary phát structured warning `INGESTION_OBSERVABILITY_WRITE_FAILED` với context bounded: `runId`, `sourceFileId`, partner, stage, error code. Warning không chứa raw row, secret hoặc traceback và không làm fail ingestion. |
| Schedules UI | `View runtime details` đọc payload hiện tại của `/api/v1/automation/jobs`, polling 3 giây, hiển thị stage/outcome, snapshot cuối, duration, counter, quality/error và runtime context. |
| Legacy/recovery | Run thiếu summary hiển thị `No persisted snapshot yet`; retry/recovery vẫn dùng flow hiện tại. Config review là review gate, không phải active error; sau terminal outcome, event được đánh dấu resolved và current error được dọn khỏi projection. |

## Contract hiển thị

- Snapshot active là boundary-level theo source unit hoặc terminal, không phải
  một write sau từng batch.
- `FINALIZING` được giữ trong telemetry thô để truy vết boundary. Schedules
  hiển thị terminal outcome rõ ràng: `COMPLETED` hoặc `COMPLETED WITH REJECTS`,
  để không gây hiểu nhầm là stage còn đang chạy.
- `PARTIAL` phản ánh kết quả ingestion có reject; không bị suy diễn thành
  `COMPLETED` trong runtime state.
- Event timeline chỉ giữ các mốc có ý nghĩa; cảnh báo thiếu config được phân
  biệt với lỗi runtime và biến mất khỏi active error sau khi review hoàn tất.

## Quyết định phạm vi

- Schedules là surface chính; không tạo Operations page mới.
- Giữ taxonomy hiện tại, không tách `PROCESSING` thành stage mới.
- Không thêm schema/index/migration, không đổi production default hoặc
  `fast_mode`, và không đổi ingestion/reconciliation semantics.
- Không có SQL rewrite an toàn được xác định. Memory candidate không đạt gate;
  baseline hiện tại được giữ nguyên. `fast_mode=true` chỉ dùng chẩn đoán.

## Acceptance

- Backend serialize đủ component timings và harden lỗi persist telemetry.
- Frontend hiển thị current stage/outcome, counter, timing, last snapshot,
  quality/error và fallback cho legacy run.
- Counter invariant, duplicate, quarantine, retry, partial failure và recovery
  vẫn giữ nguyên.
- Benchmark 100k không có candidate hợp lệ để promote; raw evidence được giữ
  trong các report benchmark của Sprint 4.

## Verification cuối sprint

- Backend targeted tests: `18 passed` (`recovery_view` và
  `post_approval_reconciliation`).
- Frontend typecheck, lint và production build: pass.
- Dashboard UI E2E: `11 passed` với một worker.
- API đã rebuild bằng Docker; `/api/v1/automation/jobs` xác nhận projection
  terminal, error đã được dọn và config-review events ở trạng thái resolved.

Xem [Sprint 4 index](sprint-4-index.md) để tìm report benchmark và evidence.
