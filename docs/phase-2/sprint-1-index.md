# Sprint 1 — Core Idempotency Index

Sprint 1 thiết lập nền tảng chống trùng cho ingestion: claim file/fetch unit,
derive transaction key, ghi batch conflict-safe và thống kê outcome ổn định khi
retry hoặc replay.

## 1. Luồng xử lý cốt lõi

```text
input file / API fetch unit
  → fileHash / fetchUnitKey claim
  → mapping, reader và row normalization
  → derive ingestion_key
  → validate và batch write PostgreSQL
  → duplicate/error accounting
  → file status và ingestion outcome
```

File replay được chặn trước row ingestion. Transaction duplicate được xử lý ở
database boundary để retry không phụ thuộc vào read-before-write.

## 2. Bốn lớp idempotency

| Lớp | Identity | Bảo vệ |
|---|---|---|
| File | `sha256(content)` → `fileHash` | Cùng nội dung không tạo file claim hoặc transaction mới |
| Fetch unit | `sourceUnitKey` explicit hoặc hash metadata fetch | Cùng API page/cursor/window không bị ingest lại |
| Transaction | `identify + ingestion_key` | Cùng transaction contract key chỉ có một bản ghi PostgreSQL |
| Batch/outcome | inserted / duplicate / failed counters | Retry một phần không làm mất thống kê hoặc fail cả batch hợp lệ |

## 3. Các invariant phải giữ

- File claim và fetch-unit claim phải atomic; race chỉ cho phép một canonical
  claim thành công.
- `ingestion_key` phải deterministic: ưu tiên identifier ổn định từ partner,
  fallback theo contract rõ ràng, không sinh key ngẫu nhiên.
- PostgreSQL là transaction store duy nhất; unique constraint trên
  `(identify, ingestion_key)` là duplicate authority.
- Batch write dùng conflict-safe persistence (`ON CONFLICT DO NOTHING`) và
  trả số lượng inserted/duplicate/failed thực tế.
- Duplicate là outcome hợp lệ, không phải lỗi fatal; file duplicate,
  fetch-unit replay, transaction duplicate và persistence error phải phân biệt.
- Retry sau partial failure phải cho cùng kết quả cuối như chạy thành công từ
  đầu.
- Mapping/reader/validator chỉ chuẩn hóa và kiểm tra dữ liệu; duplicate
  authority không bị đẩy lên fuzzy matching hoặc UI.

## 4. Runtime outcomes

| Outcome | Ý nghĩa vận hành |
|---|---|
| `COMPLETED` | Pipeline kết thúc; có thể kèm duplicate counters |
| `FILE_DUPLICATE` | File hash đã được claim/xử lý trước đó |
| `FETCH_UNIT_REPLAY` | API fetch unit đã tồn tại hoặc đã hoàn tất |
| `transaction_duplicate` / `batch_conflict` | Database bỏ qua row conflict-safe và ghi nhận trong stats |
| `FAILED` | Lỗi non-duplicate hoặc lỗi pipeline cần recovery |

## 5. Canonical implementation map

| Capability | Module chính |
|---|---|
| Pipeline orchestration | [`src/pipeline/ingestion_pipeline.py`](../../src/pipeline/ingestion_pipeline.py) |
| File/fetch-unit claim | [`src/pipeline/file_claim.py`](../../src/pipeline/file_claim.py) và [`src/infrastructure/ingestion/file_repository.py`](../../src/infrastructure/ingestion/file_repository.py) |
| Row processing | [`src/pipeline/row_pipeline.py`](../../src/pipeline/row_pipeline.py), [`row_processor.py`](../../src/pipeline/row_processor.py), [`src/normalizer/`](../../src/normalizer/) và [`src/validators/`](../../src/validators/) |
| Batch persistence | [`src/pipeline/batch_writer.py`](../../src/pipeline/batch_writer.py) và [`src/infrastructure/partner_transaction/repository.py`](../../src/infrastructure/partner_transaction/repository.py) |
| Database invariant | [`src/infrastructure/persistence/postgres_schema.py`](../../src/infrastructure/persistence/postgres_schema.py) và [`alembic/versions/0002_ingestion_idempotency.py`](../../alembic/versions/0002_ingestion_idempotency.py) |
| Outcome accounting | [`src/pipeline/run_state.py`](../../src/pipeline/run_state.py) và [`src/pipeline/finalizer.py`](../../src/pipeline/finalizer.py) |

## 6. Phạm vi và evidence

Sprint 1 không sở hữu reconciliation engine, frontend, AI hay workflow
orchestration. Các scenario schema, file replay, fetch-unit claim, partial
batch, migration và PostgreSQL-only storage được ghi trong
[Sprint 1 evaluation](sprint-1-eval-benchmark.md) và
[benchmark run](sprint-1-eval-benchmark-run.md).
