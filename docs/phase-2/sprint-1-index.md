# Sprint 1 — Core Function Index

> Chỉ mục các hàm xử lý trực tiếp core logic của Sprint 1: claim idempotency,
> row processing, transaction duplicate protection và outcome accounting.

## 1. Ingestion orchestration

| Function | Location | Handles | Handoff |
|---|---|---|---|
| `build_ingestion_pipeline` | [`composition.py:11`](../../src/infrastructure/ingestion/composition.py#L11) | Production dependency wiring | `IngestionPipeline.execute` |
| `IngestionPipeline.execute` | [`ingestion_pipeline.py:170`](../../src/pipeline/ingestion_pipeline.py#L170) | Application command entry point | `_process_file` |
| `IngestionPipeline._process_file` | [`ingestion_pipeline.py:208`](../../src/pipeline/ingestion_pipeline.py#L208) | Điều phối claim → config → row phase → finalize | `FileClaimService`, `ConfigPreparationService`, `RowPipelineExecutor`, `IngestionRunFinalizer` |

## 2. File và fetch-unit idempotency

| Function | Location | Core behavior | Result |
|---|---|---|---|
| `FileClaimService.compute_file_hash` | [`file_claim.py:30`](../../src/pipeline/file_claim.py#L30) | Hash bytes của file bằng SHA-256 theo chunk | `fileHash` |
| `FileClaimService.derive_fetch_unit_key` | [`file_claim.py:40`](../../src/pipeline/file_claim.py#L40) | Canonicalize partner/workflow/date/source/page/cursor rồi hash | `fetchUnitKey` hoặc `ValueError` |
| `FileClaimService.claim` | [`file_claim.py:73`](../../src/pipeline/file_claim.py#L73) | Claim atomically, phân biệt file replay và fetch-unit replay | `FileClaimResult` |
| `find_by_file_hash` | [`file_repository.py:23`](../../src/infrastructure/ingestion/file_repository.py#L23) | Fast lookup file đã ingest | Existing claim |
| `find_by_fetch_unit_key` | [`file_repository.py:48`](../../src/infrastructure/ingestion/file_repository.py#L48) | Lookup API fetch-unit đã tồn tại | Existing fetch-unit |
| `reclaim_failed_by_file_hash` | [`file_repository.py:26`](../../src/infrastructure/ingestion/file_repository.py#L26) | Mở lại claim `FAILED` một cách atomic | `PROCESSING` claim |
| `create_or_get_by_file_hash` | [`file_repository.py:54`](../../src/infrastructure/ingestion/file_repository.py#L54) | Create claim hoặc resolve race qua unique index | `(record, created)` |

## 3. Mapping, normalize và transaction key

| Function | Location | Core behavior | Handoff |
|---|---|---|---|
| `ConfigPreparationService.prepare` | [`config_preparation.py:30`](../../src/pipeline/config_preparation.py#L30) | Resolve mapping theo partner/type/version; xử lý approval boundary | Reader + normalizer config |
| `create_reader` | [`readers/__init__.py:11`](../../src/readers/__init__.py#L11) | Chọn CSV/Excel/JSON reader và cung cấp row iterator | `RowPipelineExecutor` |
| `TransactionNormalizer.normalize` | [`normalizer.py:71`](../../src/normalizer/normalizer.py#L71) | Map source columns, convert type và collect row errors | `NormalizationResult` |
| `TransactionNormalizer.build_fast_dict` | [`normalizer.py:469`](../../src/normalizer/normalizer.py#L469) | Build dict cho fast mode | `RowProcessor` |
| `TransactionNormalizer.build_canonical` | [`normalizer.py:529`](../../src/normalizer/normalizer.py#L529) | Build typed canonical transaction | `RowProcessor` |
| `Validator.validate` | [`validator.py:63`](../../src/validators/validator.py#L63) | Validate required fields, amount, date và status; không lookup duplicate | `ValidationResult` |
| `RowPipelineExecutor.run` | [`row_pipeline.py:72`](../../src/pipeline/row_pipeline.py#L72) | Wire reader, pure validator, writer và row coordinator; DB là duplicate authority | `RowBatchMetrics` |
| `RowProcessor.derive_ingestion_key` | [`row_processor.py:52`](../../src/pipeline/row_processor.py#L52) | Ưu tiên `id`, fallback `trace`; thiếu cả hai thì reject | `ingestion_key` |
| `RowProcessor.process` | [`row_processor.py:63`](../../src/pipeline/row_processor.py#L63) | Normalize → build → validate → derive key → build container; fast mode trả `FastDataContainer` | `RowProcessingResult` |

## 4. Batch và transaction duplicate protection

| Function | Location | Core behavior | Handoff |
|---|---|---|---|
| `RowBatchCoordinator.run` | [`row_batch_coordinator.py:85`](../../src/pipeline/row_batch_coordinator.py#L85) | Iterate rows, buffer batch, drain writes và ghi row/batch errors | `IngestionRunState` |
| `RowBatchCoordinator._flush_batch` | [`row_batch_coordinator.py:146`](../../src/pipeline/row_batch_coordinator.py#L146) | Emit persist stage và submit một batch | `BatchWriteCoordinator` |
| `BatchWriteCoordinator._write` | [`batch_writer.py:20`](../../src/pipeline/batch_writer.py#L20) | Gọi repository `insert_many(..., detailed=True)` | `BatchInsertResult` |
| `BatchWriteCoordinator.submit` / `drain` | [`batch_writer.py:27`](../../src/pipeline/batch_writer.py#L27) | Giới hạn concurrency và bảo đảm mọi write task hoàn tất | Batch results |
| `data_container_to_row` | [`repository.py:34`](../../src/infrastructure/partner_transaction/repository.py#L34) | Map domain model sang 22 PostgreSQL columns | SQL row |
| `DataContainerRepository.insert_many` | [`repository.py:172`](../../src/infrastructure/partner_transaction/repository.py#L172) | Chuẩn hóa docs, gọi conflict-safe persistence và tính duplicates | `BatchInsertResult` |
| `DataContainerRepository._insert_rows_conflict_safe` | [`repository.py:139`](../../src/infrastructure/partner_transaction/repository.py#L139) | `COPY` vào staging rồi `INSERT ... ON CONFLICT DO NOTHING` | Inserted count |
| `PartnerTransactionTable` | [`postgres_schema.py:12`](../../src/infrastructure/persistence/postgres_schema.py#L12) | Enforce `NOT NULL ingestion_key` và unique `(identify, ingestion_key)` | Database invariant |
| `upgrade` migration `0002` | [`0002_ingestion_idempotency.py:19`](../../alembic/versions/0002_ingestion_idempotency.py#L19) | Backfill key lịch sử, reject duplicate và bật constraint | Safe schema |

## 5. Outcome accounting và lifecycle

| Function | Location | Core behavior | Output |
|---|---|---|---|
| `IngestionRunState.record_batch_result` | [`run_state.py:70`](../../src/pipeline/run_state.py#L70) | Cộng inserted/duplicates/failed và tạo error category tương ứng | Stats + errors |
| `IngestionRunState.quality_counters` | [`run_state.py:88`](../../src/pipeline/run_state.py#L88) | Chuẩn hóa input/persisted/rejected/duplicate/failed counters | API/file payload |
| `IngestionRunFinalizer.complete` | [`finalizer.py:16`](../../src/pipeline/finalizer.py#L16) | Persist stats, stage summary và status `COMPLETED` | Completed outcome |
| `IngestionRunFinalizer.fail` | [`finalizer.py:42`](../../src/pipeline/finalizer.py#L42) | Best-effort persist lỗi, stats và status `FAILED`; generic exception dùng `ingestion_error` | Failed outcome |

## 6. Core trace order

```text
IngestionPipeline._process_file
  → FileClaimService.claim
  → ConfigPreparationService.prepare
  → RowPipelineExecutor.run
  → RowProcessor.process
  → RowBatchCoordinator._flush_batch
  → BatchWriteCoordinator._write
  → DataContainerRepository.insert_many
  → _insert_rows_conflict_safe
  → IngestionRunState.record_batch_result
  → IngestionRunFinalizer.complete / fail
```

Đây là index của các hàm core; các phần reconciliation, frontend, scheduler
downstream và test scenario không nằm trong file này.
