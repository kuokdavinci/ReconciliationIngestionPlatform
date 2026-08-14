# Plan 1 — Idempotency cho ingestion

## Mục tiêu

Đảm bảo ingestion có thể retry an toàn, chạy lại cùng file an toàn, retry API an toàn và partial failure không tạo thêm bản ghi partner trùng. Phạm vi chỉ gồm fetch/ingestion/persistence; không thay đổi logic đối soát, frontend, scheduler orchestration ngoài phần truyền metadata idempotency, hoặc AI.

## Bối cảnh codebase hiện tại

- `src/pipeline/ingestion_pipeline.py` đã có SHA-256 file hash và early return khi `ReconciliationFile.fileHash` đã tồn tại.
- `src/infrastructure/persistence/mongo_indexes.py` có unique index cho `reconciliation_file.fileHash`; transaction thực tế được lưu trong PostgreSQL.
- `ingestion_key` đã là field first-class trong canonical model và PostgreSQL schema; batch insert dùng `ON CONFLICT DO NOTHING`.
- `DataContainerRepository`, `InternalTransactionRepository` và `ReconciliationResultRepository` đều là PostgreSQL-only; MongoDB không lưu dữ liệu giao dịch.
- `ReconciliationFileRepository` có idempotent create-or-get dựa trên unique file hash/fetch-unit key.
- Unit/contract tests đã cover atomic claim, duplicate-safe batch result, replay, partial retry và fetch-unit key; real database scenarios được tách trong integration test.

## Phạm vi và nguyên tắc

- Chỉ xử lý ingest idempotency ở layer dữ liệu và pipeline.
- Không dùng fuzzy matching để quyết định duplicate transaction.
- Không overwrite bản ghi hợp lệ trừ khi partner có version/update rule rõ ràng và được mô tả riêng.
- Duplicate là một outcome hợp lệ của pipeline, không phải lỗi fatal.
- PostgreSQL là store duy nhất cho partner transaction, internal transaction và reconciliation result; MongoDB chỉ giữ config, file claim và workflow metadata.
- Mọi thay đổi phải đi theo TDD: viết test failing trước, sau đó implement đủ nhỏ để test pass, cuối cùng refactor.

## Định nghĩa idempotency

1. **File idempotency**
   - Khóa: `sha256(content)`.
   - Cùng nội dung file không được tạo thêm file record hay transaction mới.
   - Claim file phải atomic để tránh race giữa các worker.

2. **Fetch-unit idempotency**
   - Khóa phải mô tả một lần fetch ổn định: `partner + workflow_type + file_type + reconciliation_date + source endpoint + page/cursor/window + config_version`.
   - Nếu cùng page/cursor được fetch lại, kết quả persist không được nhân đôi.
   - Metadata fetch unit phải được truyền xuyên qua pipeline để phục vụ logging, stats và reprocess.

3. **Transaction idempotency**
   - Khóa chính của transaction là `ingestion_key` ổn định theo partner contract.
   - Ưu tiên key do partner cung cấp nếu có tính ổn định và duy nhất.
   - Nếu partner không cung cấp key, key phải được canonical hóa từ business fields đã được cấu hình rõ trong mapping, không dùng full row fuzzy compare.
   - Hai record hợp lệ chỉ khác các field ngoài contract key vẫn phải được xem là khác nhau nếu partner contract nói vậy.

## Quyết định kỹ thuật

1. Thêm `ingestion_key` vào model canonical transaction.
   - `DataContainer` phải giữ `ingestion_key` như field first-class, có serialize/deserialize rõ ràng.
   - `PartnerData` không được dùng thay thế cho transaction identity.

2. Thêm bảo vệ database level cho transaction.
   - PostgreSQL: unique constraint/index trên `(identify, ingestion_key)`.
   - Không persist transaction vào MongoDB.
   - Batch insert phải dùng cơ chế conflict-safe và trả về số lượng inserted/duplicate.

3. Chuẩn hóa kết quả persist.
   - `insert_many()` phải phân biệt `inserted`, `duplicate`, `failed`.
   - Duplicate không được làm fail cả batch nếu phần còn lại vẫn persist được.
   - Khi backend hỗ trợ `ON CONFLICT DO NOTHING`, pipeline phải đọc số bản ghi thật sự inserted, không suy ra từ batch size.

4. Atomic claim cho file.
   - `ReconciliationFile` cần thao tác claim/status transition an toàn khi hai worker cùng xử lý một file.
   - Nếu file đã được claim/processed, worker thứ hai phải nhận duplicate outcome rõ ràng, không tạo file record mới.

5. Replay contract.
   - Chạy lại cùng file, cùng fetch unit, hoặc cùng transaction key phải cho kết quả cuối ổn định.
   - Retry sau lỗi giữa chừng phải giữ được trạng thái idempotent: kết quả cuối không phụ thuộc số lần retry.

## Contract cho agent

### Input contract

- Input của pipeline là file path, partner, workflow_type, file_type, reconciliation_date, config_version, và metadata fetch unit nếu có.
- `ingestion_key` phải được tính trước khi persist transaction.
- Nếu không tính được `ingestion_key`, record đó phải bị reject theo rule rõ ràng, không được fallback sang key ngẫu nhiên.

### Output contract

- `IngestionResult.file_record` phải trỏ tới record file canonical đã tồn tại hoặc mới tạo.
- `ProcessingStats` phải phản ánh đúng `total_rows`, `success_rows`, `failed_rows`; nếu test/contract mới thêm counter duplicate thì phải định nghĩa rõ trong `src/core/types.py`.
- Errors phải phân biệt `file_duplicate`, `transaction_duplicate`, `batch_conflict`, `claim_conflict`, `persistence_error`.
- Duplicate file không được làm phát sinh `insert_many()`.

### Repository contract

- `ReconciliationFileRepository`:
  - Có method/flow atomic claim hoặc idempotent create-or-get.
  - Có thể tìm theo `file_hash`.
  - Không tạo record trùng khi file đã tồn tại.
- `DataContainerRepository`:
  - Có method insert conflict-safe.
  - Có method lookup theo `ingestion_key` hoặc lookup helper phục vụ validator nếu validator còn cần read-before-write.
  - Có thể trả về kết quả batch chi tiết.

### Schema contract

- PostgreSQL `partner_transaction` phải có cột `ingestion_key`.
- Index/constraint phải đảm bảo uniqueness theo transaction identity đã chốt.
- Migration phải backfill an toàn, hoặc ít nhất phải chứng minh được dữ liệu cũ không vi phạm constraint trước khi bật unique index.

## Hướng tiếp cận TDD

### Pha 1 — Red tests cho behavior hiện tại đang thiếu

Viết test trước cho các case sau:

- Replay cùng file hash chỉ tạo một file record và không insert transaction mới.
- Concurrent create/claim cùng file không sinh hai record file.
- Insert batch có duplicate chỉ insert phần mới, duplicate không làm fail cả batch.
- Cùng `identify + ingestion_key` qua nhiều lần persist chỉ có một transaction cuối cùng.
- Retry sau lỗi giữa batch vẫn cho kết quả cuối giống chạy thành công từ đầu.
- File duplicate, fetch-unit duplicate, transaction duplicate phải có error code riêng.

### Pha 2 — Implement nhỏ nhất để pass

- Bổ sung `ingestion_key` vào model và serializer.
- Bổ sung unique constraint/index transaction trong PostgreSQL.
- Sửa repository batch insert sang conflict-safe path.
- Sửa pipeline để tính key, truyền key, và xử lý duplicate outcome.
- Sửa file repository để claim atomic hoặc idempotent create-or-get.

### Pha 3 — Refactor và siết contract

- Loại bỏ Mongo fallback khỏi transaction repository.
- Đưa helper key derivation vào một nơi duy nhất.
- Chuẩn hóa error payload, counters, và log fields.
- Bảo đảm tests mô tả contract, không phụ thuộc chi tiết implementation.

## File dự kiến modified

- `src/pipeline/ingestion_pipeline.py` — tạo/truyền `ingestion_key`, xử lý duplicate outcome, atomic file claim, và batch result.
- `src/domain/partner_transaction/models.py` và `src/infrastructure/partner_transaction/repository.py` — thêm `ingestion_key`, cập nhật serialize/deserialize, repository insert conflict-safe.
- `src/infrastructure/persistence/postgres_schema.py` — thêm cột và unique constraint/index cho `partner_transaction`.
- `alembic/versions/<new>_ingestion_idempotency.py` — migration thêm cột, backfill, kiểm tra an toàn, và tạo index/constraint.
- `src/domain/ingestion/models.py` và `src/infrastructure/ingestion/file_repository.py` — atomic claim/idempotent create-or-get và status transition an toàn.
- `src/infrastructure/persistence/mongo_indexes.py` — chỉ giữ index Mongo cho file claim, config và workflow metadata.
- `src/core/constants.py` hoặc `src/core/types.py` — định nghĩa helper contract cho key derivation, duplicate codes, và counters nếu cần mở rộng.
- `tests/test_ingestion_pipeline.py` — test TDD cho replay file, duplicate transaction, partial retry, claim race.
- `tests/test_ingestion_integration.py` — test end-to-end cho duplicate-safe flow trên batch thật.
- `tests/test_models.py` — test repository/model serialize, lookup, and batch conflict behavior.
- `tests/test_indexes.py` hoặc test migration liên quan — test index/constraint contract.

## Ngoài phạm vi

- Không sửa `src/reconciliation/engine.py`.
- `src/reconciliation/scope.py` chỉ được sửa để đọc transaction counts qua PostgreSQL repository.
- Không sửa frontend, analytics, AI prompt/provider, hay reconciliation UI.
- Không đổi nghĩa business của transaction trừ khi nó liên quan trực tiếp tới key stability.

## Tiêu chí nghiệm thu

- Replay cùng file hash không tăng số transaction và không tạo file record mới.
- Replay cùng fetch unit/page/cursor không tạo thêm data trùng.
- Cùng transaction key qua nhiều lần ingest chỉ có một bản ghi canonical.
- Hai transaction hợp lệ chỉ khác ngoài contract key không bị gộp nhầm.
- Retry sau lỗi giữa batch cho kết quả cuối giống chạy thành công từ đầu.
- Duplicate outcome được thống kê rõ ràng, không biến thành fatal error.
- Database schema và tests chứng minh được contract idempotency, không chỉ mô tả bằng comment.

## Definition of Done

- Test suite mới cho các case idempotency quan trọng đều pass.
- Migration/schema/index đã được cập nhật và có đường lui rõ ràng nếu dữ liệu cũ vi phạm constraint.
- Pipeline và repository không còn phụ thuộc vào read-before-write thuần để chống duplicate transaction.
- Contract trong plan khớp với code, không có thuật ngữ mơ hồ như "gần giống" hay "fuzzy".
