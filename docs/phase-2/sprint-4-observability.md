# Plan 4 — Observability cho ingestion runtime

## Mục tiêu

Xác định pipeline đang ở đâu, lỗi ở bước nào, số lượng và thời gian xử lý của từng run; phản ánh đúng partial failure. Chỉ quan sát fetch/ingestion runtime, không thay đổi logic đối soát, frontend hoặc AI.

## Đối chiếu hiện trạng

- `src/logging/logger.py` đã có event file/row và JSON formatter.
- `src/models/partner_runtime_run.py`/`src/services/runtime_runs.py` đã có trạng thái unified cho scheduler, nhưng state hiện còn gắn với flow tiếp tục sang reconciliation.
- `IngestionPipeline` có timing nội bộ và ghi `PERF_INGEST` qua logger; metrics chưa được persist theo stage và chưa có checkpoint/attempt correlation đầy đủ.
- `src/scheduler/jobs.py` cập nhật runtime status nhưng chưa ghi stage-level counts/errors/fetch metadata thống nhất.

## Quyết định đề xuất

1. Chuẩn hóa stage ingest: `FETCHING`, `READING`, `NORMALIZING`, `VALIDATING`, `PERSISTING`, `QUARANTINING`, `COMPLETED`/`FAILED` (partial là trạng thái riêng, không phải completed).
2. Dùng một `run_id` xuyên suốt fetch → ingest; mỗi event bắt buộc có partner, source unit/file, stage, attempt, timestamp và error code (không log credential/raw sensitive data).
3. Persist stage summary trong runtime run/file record: input, valid, rejected, duplicate, persisted, quarantined, current unit, current stage, started/finished/duration, last error và checkpoint before/after.
4. Giữ structured logs làm chi tiết, dùng persisted summaries để truy vấn vận hành. Không thêm dashboard UI trong scope hiện tại; API read-only chỉ bổ sung khi cần kiểm tra backend.
5. Đưa integration/E2E cases vào test matrix: retry, duplicate, partial failure, invalid record, schema change và 100k records; benchmark phải đo stage duration/memory và ngưỡng cần thống nhất trước khi pass.

## File dự kiến modified

- `src/core/enums.py` — thêm ingestion stage/run outcome enums nếu chưa có abstraction phù hợp.
- `src/core/types.py` — thêm stage metrics và run counters dùng chung.
- `src/models/partner_runtime_run.py` — thêm stage history/current stage, attempt, error và ingest metrics.
- `src/services/runtime_runs.py` — helper update stage/counters/error theo atomic update.
- `src/pipeline/ingestion_pipeline.py` — emit/persist lifecycle theo stage và partial status; gắn run/source context.
- `src/scheduler/jobs.py` — truyền run context, ghi fetch stage/result và không che khuất lỗi ingest.
- `src/logging/logger.py` — mở rộng event types/fields cho stage, batch, checkpoint và quarantine.
- `src/models/reconciliation_file.py` — lưu lifecycle summary ở file-level.
- `src/models/indexes.py` — index theo partner/stage/status/time cho truy vấn operational.
- `tests/test_logger.py`, `tests/test_ingestion_integration.py`, `tests/test_api_automation_run.py`, `tests/test_e2e_100k_records.py` — test event schema, state transition, count reconciliation và performance threshold.

## File không thuộc scope

Không sửa `src/reconciliation/engine.py`, reconciliation API/result, `frontend-next/`, `src/analysis/`, insights, copilot hoặc các provider/prompt AI. Nếu scheduler hiện đang gọi reconciliation, chỉ ghi nhận ingest completed trước downstream call; không thay đổi nội dung đối soát.

## Tiêu chí nghiệm thu

- Có thể xác định stage hiện tại và lỗi cuối cùng của từng run.
- Counts giữa các stage khớp và phân biệt rejected/duplicate/persisted.
- Partial failure không mang status `COMPLETED`.
- Retry/duplicate/invalid/schema-change có integration hoặc E2E coverage.
- Benchmark 100.000 records có số liệu stage-level và không làm thay đổi kết quả ingestion hiện tại.
