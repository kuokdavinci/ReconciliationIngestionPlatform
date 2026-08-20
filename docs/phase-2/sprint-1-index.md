# Sprint 1 — Core Idempotency Index

Sprint 1 thiết lập nền tảng chống trùng cho ingestion: claim file/fetch unit,
derive transaction key, ghi batch conflict-safe và thống kê outcome ổn định khi
retry hoặc replay.

## 1. Luồng xử lý cốt lõi

| Function | Location | Handles | Handoff |
|---|---|---|---|
| `build_ingestion_pipeline` | [`composition.py:11`](../../src/infrastructure/ingestion/composition.py#L11) | Production dependency wiring | `IngestionPipeline.execute` |
| `IngestionPipeline.execute` | [`ingestion_pipeline.py:296`](../../src/pipeline/ingestion_pipeline.py#L296) | Application command entry point | `_process_file` |
| `IngestionPipeline._process_file` | [`ingestion_pipeline.py:588`](../../src/pipeline/ingestion_pipeline.py#L588) | Điều phối claim → config → quality gate → row phase → finalize | `FileClaimService`, `ConfigPreparationService`, `FileQualityGate`, `RowPipelineExecutor`, `IngestionRunFinalizer` |

File replay được chặn trước row ingestion. Transaction duplicate được xử lý ở
database boundary để retry không phụ thuộc vào read-before-write.

## 2. Bốn lớp idempotency

| Lớp | Identity | Bảo vệ |
|---|---|---|
| File | `sha256(content)` → `fileHash` | Cùng nội dung không tạo file claim hoặc transaction mới |
| Fetch unit | `sourceUnitKey` explicit hoặc hash metadata fetch | Cùng API page/cursor/window không bị ingest lại |
| Transaction | `identify + ingestion_key` | Cùng transaction contract key chỉ có một bản ghi PostgreSQL |
| Batch/outcome | inserted / duplicate / failed counters | Retry một phần không làm mất thống kê hoặc fail cả batch hợp lệ |

| Function | Location | Core behavior | Handoff |
|---|---|---|---|
| `ConfigPreparationService.prepare` | [`config_preparation.py:30`](../../src/pipeline/config_preparation.py#L30) | Resolve mapping theo partner/type/version; xử lý approval boundary | Reader + normalizer config |
| `create_reader` | [`readers/__init__.py:11`](../../src/readers/__init__.py#L11) | Chọn CSV/Excel/JSON reader và cung cấp row iterator | `RowPipelineExecutor` |
| `TransactionNormalizer.normalize` | [`normalizer.py:106`](../../src/normalizer/normalizer.py#L106) | Map source columns, convert type và collect row errors | `NormalizationResult` |
| `TransactionNormalizer.build_fast_dict` | [`normalizer.py:540`](../../src/normalizer/normalizer.py#L540) | Build dict cho fast mode | `RowProcessor` |
| `TransactionNormalizer.build_canonical` | [`normalizer.py:609`](../../src/normalizer/normalizer.py#L609) | Build typed canonical transaction | `RowProcessor` |
| `Validator.validate` | [`validator.py:29`](../../src/validators/validator.py#L29) | Validate required fields, amount, date và status; không lookup duplicate | `QualityEvaluation` |
| `RowPipelineExecutor.run` | [`row_pipeline.py:73`](../../src/pipeline/row_pipeline.py#L73) | Wire reader, pure validator, writer và row coordinator; DB là duplicate authority | `RowBatchMetrics` |
| `RowProcessor.derive_ingestion_key` | [`row_processor.py:76`](../../src/pipeline/row_processor.py#L76) | Ưu tiên `id`, fallback `trace`; thiếu cả hai thì reject | `ingestion_key` |
| `RowProcessor.process` | [`row_processor.py:87`](../../src/pipeline/row_processor.py#L87) | Normalize → build → validate → derive key → build container; fast mode trả `FastDataContainer` | `RowOutcome` |

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

| Function | Location | Core behavior | Handoff |
|---|---|---|---|
| `RowBatchCoordinator.run` | [`row_batch_coordinator.py:88`](../../src/pipeline/row_batch_coordinator.py#L88) | Iterate rows, buffer batch, drain writes và ghi row/batch errors | `IngestionRunState` |
| `RowBatchCoordinator._flush_batch` | [`row_batch_coordinator.py:167`](../../src/pipeline/row_batch_coordinator.py#L167) | Emit persist stage và submit một batch | `BatchWriteCoordinator` |
| `BatchWriteCoordinator._write` | [`batch_writer.py:21`](../../src/pipeline/batch_writer.py#L21) | Gọi typed repository port và kiểm tra batch accounting | `BatchWriteResult` |
| `BatchWriteCoordinator.submit` / `drain` | [`batch_writer.py:44`](../../src/pipeline/batch_writer.py#L44) | Giới hạn concurrency và bảo đảm mọi write task hoàn tất | Batch results |
| `data_container_to_row` | [`mappers.py:34`](../../src/infrastructure/partner_transaction/mappers.py#L34) | Map domain model sang 22 PostgreSQL columns | SQL row |
| `DataContainerRepository.insert_many` | [`repository.py:205`](../../src/infrastructure/partner_transaction/repository.py#L205) | Chuẩn hóa docs, atomic insert, bulk classify equivalent/conflicting duplicates | `BatchWriteResult` |
| `DataContainerRepository._insert_rows_conflict_safe` | [`repository.py:86`](../../src/infrastructure/partner_transaction/repository.py#L86) | Ordered staging + atomic `INSERT ... ON CONFLICT DO NOTHING RETURNING` | Inserted/conflict-key counts |
| `PartnerTransactionTable` | [`postgres_schema.py:12`](../../src/infrastructure/persistence/postgres_schema.py#L12) | Enforce `NOT NULL ingestion_key` và unique `(identify, ingestion_key)` | Database invariant |
| `upgrade` migration `0002` | [`0002_ingestion_idempotency.py:19`](../../alembic/versions/0002_ingestion_idempotency.py#L19) | Backfill key lịch sử, reject duplicate và bật constraint | Safe schema |

| Outcome | Ý nghĩa vận hành |
|---|---|
| `COMPLETED` | Pipeline kết thúc; có thể kèm duplicate counters |
| `FILE_DUPLICATE` | File hash đã được claim/xử lý trước đó |
| `FETCH_UNIT_REPLAY` | API fetch unit đã tồn tại hoặc đã hoàn tất |
| `transaction_duplicate` / `batch_conflict` | Database bỏ qua row conflict-safe và ghi nhận trong stats |
| `FAILED` | Lỗi non-duplicate hoặc lỗi pipeline cần recovery |

| Function | Location | Core behavior | Output |
|---|---|---|---|
| `IngestionRunState.record_batch_result` | [`run_state.py:147`](../../src/pipeline/run_state.py#L147) | Cộng inserted/duplicates/failed và tạo error category tương ứng | Stats + errors |
| `IngestionRunState.quality_counters` | [`run_state.py:204`](../../src/pipeline/run_state.py#L204) | Chuẩn hóa input/persisted/rejected/duplicate/failed counters | API/file payload |
| `IngestionRunFinalizer.complete` | [`finalizer.py:16`](../../src/pipeline/finalizer.py#L16) | Persist stats, stage summary và status `COMPLETED` | Completed outcome |
| `IngestionRunFinalizer.fail` | [`finalizer.py:42`](../../src/pipeline/finalizer.py#L42) | Best-effort persist lỗi, stats và status `FAILED`; generic exception dùng `ingestion_error` | Failed outcome |

| Capability | Module chính |
|---|---|
| Pipeline orchestration | [`src/pipeline/ingestion_pipeline.py`](../../src/pipeline/ingestion_pipeline.py) |
| File/fetch-unit claim | [`src/pipeline/file_claim.py`](../../src/pipeline/file_claim.py) và [`src/infrastructure/ingestion/file_repository.py`](../../src/infrastructure/ingestion/file_repository.py) |
| Row processing | [`src/pipeline/row_pipeline.py`](../../src/pipeline/row_pipeline.py), [`row_processor.py`](../../src/pipeline/row_processor.py), [`src/normalizer/`](../../src/normalizer/) và [`src/validators/`](../../src/validators/) |
| Batch persistence | [`src/pipeline/batch_writer.py`](../../src/pipeline/batch_writer.py) và [`src/infrastructure/partner_transaction/repository.py`](../../src/infrastructure/partner_transaction/repository.py) |
| Database invariant | [`src/infrastructure/persistence/postgres_schema.py`](../../src/infrastructure/persistence/postgres_schema.py) và [`alembic/versions/0002_ingestion_idempotency.py`](../../alembic/versions/0002_ingestion_idempotency.py) |
| Outcome accounting | [`src/pipeline/run_state.py`](../../src/pipeline/run_state.py) và [`src/pipeline/finalizer.py`](../../src/pipeline/finalizer.py) |

```text
IngestionPipeline._process_file
  → FileClaimService.claim
  → ConfigPreparationService.prepare
  → FileQualityGate.evaluate
  → RowPipelineExecutor.run
  → RowProcessor.process
  → RowBatchCoordinator._flush_batch
  → BatchWriteCoordinator._write
  → DataContainerRepository.insert_many
  → _insert_rows_conflict_safe
  → IngestionRunState.record_batch_result
  → IngestionRunFinalizer.complete / fail
```

Sprint 1 không sở hữu reconciliation engine, frontend, AI hay workflow
orchestration. Các scenario schema, file replay, fetch-unit claim, partial
batch, migration và PostgreSQL-only storage được ghi trong
[Sprint 1 evaluation](sprint-1-eval-benchmark.md) và
[benchmark run](sprint-1-eval-benchmark-run.md).
