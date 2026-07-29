# Plan 2 — Incremental processing và recovery

## Mục tiêu

Chỉ xử lý phần dữ liệu mới/chưa hoàn tất theo từng loại nguồn, xác nhận tiến độ sau khi persistence thành công và cho phép retry an toàn. Phạm vi không bao gồm thay đổi matching/reconciliation, frontend hoặc AI.

## Đối chiếu hiện trạng

- `src/scheduler/jobs.py` hiện chạy một fetch config, ingest một local file rồi tiếp tục gọi reconciliation.
- `src/fetchers/api_fetcher.py` thực hiện một HTTP response duy nhất và lưu thành file; chưa có page/cursor/checkpoint.
- `src/fetchers/filedrop_fetcher.py` chọn file đầu tiên; chưa loại trừ file đã completed theo hash/trạng thái.
- `src/fetchers/sftp_fetcher.py` chọn file đầu tiên khi wildcard; chưa lưu remote object identity/last successful unit.
- `ReconciliationFile` có status `PENDING/PROCESSING/COMPLETED/FAILED` nhưng chưa có checkpoint theo source unit hoặc atomic resume semantics.

## Quyết định đề xuất

1. Tạo checkpoint riêng theo `(partner, fetch_config, source_type, stream_key)` để backfill không ghi đè tiến độ định kỳ.
2. API checkpoint lưu `cursor`/`next_page_token` hoặc high-water mark; chỉ advance sau khi page đã được persist thành công. Nếu API không có cursor, dùng thời gian/ID tăng dần với overlap window và idempotency.
3. File drop/SFTP lưu fingerprint, remote path, size/modified time và trạng thái `DISCOVERED → PROCESSING → COMPLETED/FAILED`. Scheduler chỉ bỏ qua file có cùng fingerprint đã completed; file failed/incomplete được retry.
4. Tách `backfill` khỏi checkpoint định kỳ bằng execution mode và explicit range. Backfill không cập nhật high-water mark của scheduled stream.
5. Recovery không resume mù từ byte offset của Excel/CSV; resume theo file/page/batch boundary, dựa trên transaction idempotency để xử lý lại boundary an toàn.
6. Không xóa/archive local source cho tới khi ingestion hoàn tất và metadata/checkpoint đã được ghi thành công.

## File dự kiến modified

- `src/models/ingestion_checkpoint.py` — model/repository checkpoint và source-unit state.
- `src/models/indexes.py` — unique index cho checkpoint stream key và index truy vấn pending/failed units.
- `src/fetchers/base.py` — mở rộng `FetchResult` với source identity, unit list, cursor/high-water mark và retry metadata.
- `src/fetchers/api_fetcher.py` — pagination/cursor, stable fetch-unit fingerprint, ghi raw response theo unit.
- `src/fetchers/filedrop_fetcher.py` — discover nhiều file, fingerprint trước khi chọn và lọc theo checkpoint.
- `src/fetchers/sftp_fetcher.py` — stable remote identity, chọn file deterministically và trả metadata cần recovery.
- `src/scheduler/jobs.py` — load checkpoint, retry unit chưa hoàn tất, advance checkpoint sau ingestion thành công; giữ backfill mode tách biệt.
- `src/pipeline/ingestion_pipeline.py` — nhận execution/source-unit context, resume ở boundary và chỉ trả completed khi persistence hoàn tất.
- `src/models/reconciliation_file.py` — lưu source-unit/checkpoint reference và các transition hợp lệ.
- `tests/test_ingestion_integration.py`, `tests/test_ingestion_pipeline.py`, `tests/test_api_automation.py`, `tests/test_api_automation_run.py` — test page failure, file failure, restart, no-skip, backfill isolation.

Nếu checkpoint cần transaction mạnh hơn Mongo hiện tại, có thể thêm migration Mongo riêng; chưa cần sửa `src/reconciliation/`.

## File không thuộc scope

Không sửa `src/reconciliation/engine.py`, `src/reconciliation/scope.py`, reconciliation result model/API, `frontend-next/`, `src/analysis/` hoặc copilot/insights.

## Tiêu chí nghiệm thu

- API bắt đầu từ unit sau cùng đã persist thành công.
- File completed không bị ingest lại khi scheduler scan.
- Lỗi giữa page/batch không advance checkpoint.
- Restart xử lý lại đúng unit chưa hoàn tất, không bỏ sót và không tạo duplicate.
- Backfill không thay đổi checkpoint scheduled.

