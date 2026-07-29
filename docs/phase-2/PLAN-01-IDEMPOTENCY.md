# Plan 1 — Idempotency cho ingestion

## Mục tiêu

Đảm bảo retry, chạy lại file, retry API và partial failure không tạo thêm dữ liệu partner trùng. Phạm vi chỉ là fetch/ingestion và persistence; không thay đổi logic đối soát, frontend hoặc AI.

## Đối chiếu hiện trạng

- `src/pipeline/ingestion_pipeline.py` đã tính SHA-256 và kiểm tra `ReconciliationFile.fileHash` trước khi chạy.
- `src/models/indexes.py` có unique index cho `reconciliation_file.fileHash`, nhưng việc `find` rồi `create` vẫn cần xử lý race condition.
- `DataContainer`/`PartnerData` đang sinh UUID mới; `Validator` kiểm tra `partnerData.trace` bằng read-before-write.
- `DataContainerRepository.insert_many()` dùng insert/COPY, chưa có khóa unique transaction-level. PostgreSQL schema hiện chưa có `ingestion_key`.

## Quyết định đề xuất

1. Dùng ba khóa độc lập:
   - **File:** `sha256(content)`; giữ unique constraint hiện tại và chuyển việc claim file thành thao tác atomic.
   - **Fetch unit:** fingerprint của partner + method + query/window + page/cursor; lưu metadata để cùng một page không bị nhận hai lần.
   - **Transaction:** `ingestion_key` ổn định. Ưu tiên ID/trace do partner cung cấp; nếu thiếu thì tạo canonical business key theo cấu hình partner, không dùng toàn bộ row gần giống nhau làm fuzzy key.
2. Để database là lớp bảo vệ cuối: unique index trên `(identify, ingestion_key)` trong PostgreSQL. Batch insert phải dùng `ON CONFLICT DO NOTHING` và trả về số inserted/duplicate.
3. Duplicate là một kết quả xử lý có thống kê, không phải lỗi làm hỏng batch. Không tự động overwrite bản ghi hợp lệ; upsert chỉ được dùng khi có quy tắc version/update rõ ràng của partner.

## File dự kiến modified

- `src/pipeline/ingestion_pipeline.py` — tạo ingestion key, truyền source/fetch context, xử lý duplicate batch và concurrent claim.
- `src/models/data_container.py` — thêm trường `ingestion_key`, chuẩn hóa cách serialize và repository insert conflict-safe.
- `src/models/postgres.py` — thêm cột/index/constraint tương ứng cho `partner_transaction`.
- `alembic/versions/<new>_ingestion_idempotency.py` — migration thêm cột, backfill/kiểm tra dữ liệu cũ và unique index.
- `src/models/reconciliation_file.py` — thêm atomic claim/retry-safe status transition và metadata fetch unit nếu chọn lưu cùng file record.
- `src/models/indexes.py` — bổ sung index Mongo tương đương cho môi trường/mock Mongo.
- `src/core/constants.py` hoặc `src/core/types.py` — định nghĩa key version và helper contract cho business key.
- `tests/test_ingestion_pipeline.py`, `tests/test_ingestion_integration.py`, `tests/test_models.py`, `tests/test_indexes.py` — test replay file/API, transaction lặp, race/partial batch và near-similar valid records.

## File không thuộc scope

Không sửa `src/reconciliation/engine.py`, `src/reconciliation/scope.py`, các router/frontend reconciliation, `frontend-next/`, `src/analysis/` và các API AI. Kết quả đối soát chỉ là downstream consumer của dữ liệu đã được ingest.

## Tiêu chí nghiệm thu

- Replay cùng file không tăng số transaction.
- Replay cùng fetch unit/page/cursor không tăng dữ liệu.
- Cùng transaction qua nhiều file chỉ có một `ingestion_key`.
- Hai transaction hợp lệ chỉ khác khóa partner định nghĩa không bị gộp nhầm.
- Retry sau lỗi giữa các batch cho kết quả cuối giống chạy thành công từ đầu.

