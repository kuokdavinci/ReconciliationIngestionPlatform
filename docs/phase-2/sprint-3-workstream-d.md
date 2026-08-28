# Sprint 3 — Workstream D: Quarantine lifecycle và source-unit recovery

**Trạng thái:** `Implemented` ở domain, application, persistence và runtime
boundary.

## Vấn đề và phạm vi

Lưu row bị route khỏi ingestion, cho phép xử lý có kiểm soát và chỉ resume
source unit khi mọi blocker đã terminal.

| D xử lý | D không xử lý |
|---|---|
| Quarantine record, lifecycle, source evidence, reprocess, retention, checkpoint-safe resume | Rule registry/quality precedence, operator queue/API policy và notifications/dashboard |

## Lifecycle contract

| Trạng thái | Vào từ | Hành động hợp lệ | Ra trạng thái |
|---|---|---|---|
| `PENDING` | Row reject/conflict hoặc retry | Claim | `REPROCESSING` |
| `REPROCESSING` | Claim thành công | Reprocess, accept existing, reject | `RESOLVED`, `PENDING` hoặc `REJECTED` |
| `RESOLVED` | Xử lý thành công | Không có mutation tiếp | Terminal |
| `REJECTED` | Operator discard | Không có mutation tiếp | Terminal |

Claim dùng atomic lease. Claim hết hạn phải được trả về `PENDING` trước khi
operator khác claim. Deterministic validation failure và retryable persistence
failure quay lại `PENDING`.

## Resolution contract

| Trường hợp | Điều kiện | Kết quả |
|---|---|---|
| Reprocess source row | Có authoritative source evidence | Shared row processor chạy lại; thành công → `RESOLVED` |
| Reprocess corrected row | Operator cung cấp `correctedRow` hợp lệ | Persist thành công → `RESOLVED`; lỗi → `PENDING` |
| `ACCEPT_EXISTING` | `existingFingerprint` khớp record hiện có | `RESOLVED` |
| `REJECT` | Có bounded operator reason | `REJECTED` |
| Resolution lỗi retryable | Dependency/persistence tạm thời lỗi | `PENDING`, giữ attempt/evidence bounded |

Source evidence lấy từ authoritative source file hoặc staged raw page. Raw row
và error evidence được sanitize/bounded trước khi lưu.

## Source-unit hold và resume

| Bước | Điều kiện bắt buộc | Kết quả |
|---|---|---|
| Hold | Có active `CONFLICTING_DUPLICATE` blocker | Không advance checkpoint, không reconcile, không cleanup |
| Resolve | Tất cả blocker ở `RESOLVED` hoặc `REJECTED` | Cho phép resume |
| Resume | Durable raw unit và checkpoint hợp lệ | Rebuild unit, reconcile phần còn lại |
| Commit | Reconcile thành công | Advance checkpoint trước raw-page/file cleanup |

Resume phải idempotent và không persist lại row conflict đã xử lý.

## Record và implementation

| Dữ liệu/Module | Vai trò |
|---|---|
| `src/domain/ingestion/quarantine.py` | State, action, transition và bounded evidence |
| `src/infrastructure/ingestion/quarantine_repository.py` | Mongo record, lease, index và history |
| `src/application/ingestion/quarantine_service.py` | Claim/resolution orchestration |
| `src/application/ingestion/quarantine_reprocessing.py` | Source-backed replay và corrected row |
| `src/application/ingestion/source_unit_orchestrator.py` | Hold/resume source unit |
| `src/application/ingestion/source_unit_resume.py` | Checkpoint-safe resume |
| `src/api/quarantine.py` | API adapter cho quarantine lifecycle |

Record chỉ giữ identifiers, status, reason/error code, source-unit correlation,
attempt counters, sanitized evidence và bounded resolution history. Terminal
records có retention window.

## Evidence

| Kiểm tra | Kết quả |
|---|---|
| Lifecycle fixture | Invalid row, correction, duplicate, reject, accept-existing, hold/resume và retention |
| Runtime wiring | Quarantine repository, source readers, adapter và resume path |
| Concurrency | Atomic claim; stale lease không được mutate bởi owner cũ |
| Recovery | Checkpoint advance trước cleanup; không duplicate persistence |
