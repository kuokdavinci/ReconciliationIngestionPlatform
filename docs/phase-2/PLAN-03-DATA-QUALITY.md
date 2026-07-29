# Plan 3 — Data quality và quarantine

## Mục tiêu

Giữ lại có cấu trúc mọi record bị reject, phân biệt lỗi record với lỗi batch, truy vết được nguồn/config và cho phép reprocess nhóm lỗi mà không chạy lại toàn bộ nguồn. Không mở rộng sang logic đối soát, frontend hay AI.

## Đối chiếu hiện trạng

- `src/normalizer/normalizer.py` và `src/validators/validator.py` đã trả về lỗi có `field`, `reason`, `row`, `trace`.
- `IngestionPipeline` hiện gom lỗi vào list/log; lỗi không được persist thành quarantine record.
- Lỗi row được continue, nhưng lỗi reader/config/persistence làm file `FAILED`; chưa có severity/phase contract thống nhất.
- `ProcessingStats` mới có `total/success/failed`; chưa phân biệt rejected, duplicate, quarantined và input reconciliation.

## Quyết định đề xuất

1. Tạo collection Mongo `ingestion_quarantine_record` cho dữ liệu lỗi linh hoạt và audit-friendly. Lưu raw row đã sanitize, source file/unit, row number/source location, partner, reconciliation date, error phase/severity/code, config version, attempt count, status và timestamps.
2. Phân loại tối thiểu:
   - `BATCH_FATAL`: file không đọc được, schema/structure không phù hợp, thiếu header hoặc lỗi config bắt buộc; dừng trước khi ghi dữ liệu sai.
   - `RECORD_REJECTED`: chỉ record lỗi; quarantine rồi tiếp tục record hợp lệ.
   - `DUPLICATE`: ghi nhận thống kê/idempotency outcome; không coi là invalid data.
3. Quarantine write phải được thực hiện theo batch và có retry/error policy. Nếu quarantine cũng thất bại, không đánh dấu file completed; giữ trạng thái failed để không mất record lỗi.
4. Reprocess dùng `quarantine_id`/query filter và mapping version mới, tạo attempt mới, không xóa lịch sử. Record sửa thành công chuyển `RESOLVED`; vẫn lỗi chuyển `REJECTED` với reason mới.
5. Chuẩn hóa counters: `input = success + rejected + duplicate` (và các record chưa hoàn tất nếu batch đang partial). Không đưa lỗi validation vào log-only path.

## File dự kiến modified

- `src/models/quarantine_record.py` — model, enum trạng thái/severity/phase và repository.
- `src/models/indexes.py` — index theo file/unit/status/partner và index phục vụ reprocess.
- `src/core/types.py` — mở rộng `ValidationError`/`ProcessingStats` với phase, code, severity và counters.
- `src/normalizer/normalizer.py` — trả error code/phase nhất quán cho lỗi normalize.
- `src/validators/validator.py` — gắn severity/code và phân biệt validation với duplicate.
- `src/pipeline/ingestion_pipeline.py` — persist quarantine theo batch, xử lý fatal-vs-record, cập nhật counters.
- `src/models/reconciliation_file.py` — lưu rejected/duplicate/quarantine counts và trạng thái batch.
- `src/api/automation.py` hoặc router ingestion mới — endpoint vận hành reprocess quarantine; chỉ thêm API backend tối thiểu, không làm frontend.
- `tests/test_validator.py`, `tests/test_normalizer.py`, `tests/test_ingestion_integration.py`, `tests/test_models.py` — test quarantine persistence, fatal structure, partial batch và reprocess.

## File không thuộc scope

Không sửa `src/reconciliation/engine.py`, các model/result của reconciliation, `frontend-next/`, `src/analysis/`, `src/api/insights.py`, `src/api/copilot.py` hoặc prompt/provider AI.

## Tiêu chí nghiệm thu

- Mỗi reject có bản ghi quarantine có thể truy vết tới file/unit/row/config.
- Record-level reject không dừng các record hợp lệ.
- Structural fatal không ghi dữ liệu sai và không thành completed.
- Có thể reprocess một nhóm quarantine bằng filter mà không đọc lại toàn bộ nguồn.
- Counters đầu vào, success, rejected, duplicate và partial được đối chiếu được.

