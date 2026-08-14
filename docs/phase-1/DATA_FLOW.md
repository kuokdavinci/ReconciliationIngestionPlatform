# Data Flow hiện tại

**Cập nhật:** 2026-08-14

Tài liệu này mô tả các flow có thể truy vết trong module hiện tại. Các chi tiết acceptance theo sprint nằm trong [Phase 2 Sprint Index](../phase-2/INDEX.md).

## 1. Ingestion file/stream

```text
FileDrop / API / SFTP
  -> FetchResult + SourceUnitMetadata
  -> source stream identity
  -> claim file/fetch unit
  -> load + validate mapping
  -> reader
  -> normalize
  -> validate / quarantine
  -> ingestion_key
  -> batch write partner_transaction
  -> checkpoint + runtime metrics
```

Các module chính:

- `src/fetchers/base.py`, `api_fetcher.py`, `filedrop_fetcher.py`, `sftp_fetcher.py` — retrieval và source-unit metadata.
- `src/application/automation/stream_identity.py` — stream/source-unit/raw-stage identity.
- `src/application/ingestion/source_unit_orchestrator.py` — sequential processing, retry, claim và checkpoint.
- `src/pipeline/ingestion_pipeline.py` — file claim, mapping, lifecycle và final status.
- `src/pipeline/row_pipeline.py`, `row_processor.py`, `row_batch_coordinator.py` — đọc/normalize/validate/batch.
- `src/infrastructure/ingestion/` và `src/infrastructure/partner_transaction/` — persistence adapters.

Mapping drift được phát hiện qua `src/config/signature.py` và `src/config/config_health.py`. Khi strict approval bật, hệ thống tạo review packet/config proposal thay vì tự ý activate mapping mới.

## 2. Checkpoint và recovery

`process_source_units()` chỉ advance checkpoint sau khi unit đã persist thành công. Khi một page/unit lỗi:

1. Runtime ghi lỗi, attempt và recovery event.
2. Checkpoint giữ unit cuối cùng đã hoàn tất.
3. Operator retry/resume từ boundary lỗi; replay dùng file hash/fetch-unit key/ingestion key để không nhân bản dữ liệu.
4. API pagination có thể stage raw pages trong GridFS trước khi review/approval.

Runtime và recovery view dùng:

- `src/application/runtime/service.py`
- `src/application/ingestion/recovery_view.py`
- `src/infrastructure/ingestion/checkpoint_repository.py`
- `src/infrastructure/ingestion/raw_page_repository.py`
- `src/domain/ingestion/checkpoints.py`, `raw_pages.py`, `retry_policy.py`

## 3. Reconciliation

Entry points:

- `run.py --reconcile YYYY-MM-DD --partner PARTNER`
- `POST /api/v1/reconciliation/run`
- `src/application/reconciliation/service.py`
- `src/reconciliation/engine.py`

Flow:

1. Chọn partner/business date theo `APP_BUSINESS_TIMEZONE`.
2. Đọc partner/internal transactions từ PostgreSQL theo batch.
3. Normalize business key qua `src/reconciliation/keys.py`.
4. Phân loại scope bằng `src/reconciliation/scope.py`.
5. Match amount/status và phân loại `MATCHED`, mismatch, missing hoặc unconfirmed.
6. Ghi `reconciliation_result` theo batch qua infrastructure repository.
7. API trả summary, result pagination, review records và insight context.

## 4. Review packet và mapping approval

```text
pending mapping/config issue
  -> review_packet
  -> raw/internal evidence
  -> scope + runtime validation
  -> draft mapping
  -> approve / keep-current / reject / send-to-studio
  -> reprocess staged pages hoặc source file
  -> reconcile
```

Các module chính:

- `src/api/review_packets.py`, `src/api/mappings.py`
- `src/application/review/actions.py`
- `src/application/review/mapping_workflow.py`
- `src/application/review/runtime_validation.py`
- `src/application/review/scope_classification.py`
- `src/application/review/raw_stream.py`
- `src/application/mapping/service.py`, `proposals.py`

Approval theo backfill gắn packet với `backfillRunId` và resume cùng parent run; không tạo một execution độc lập sau approval.

## 5. Airflow automation

```text
Airflow DAG reconciliation_ingestion
  -> select_streams
  -> mapped run_stream
  -> execute_stream()
  -> run_source_stream()
  -> fetch / ingest / checkpoint / reconcile
  -> runtime result + structured Airflow log
```

- DAG: `dags/reconciliation_ingestion.py`.
- Application entrypoint: `src/application/automation/service.py::execute_stream`.
- Stream runner: `src/application/automation/stream_runner.py::run_source_stream`.
- Airflow adapter: `src/infrastructure/workflows/airflow.py`.
- API routes: `/api/v1/automation`.

Airflow sở hữu scheduling/task state; application sở hữu business state, checkpoint, retry policy của source unit và idempotency. Compose pilot dùng `AIRFLOW_GLOBAL_SCHEDULE=none` và `AIRFLOW_TASK_RETRIES=0`.

## 6. Post-approval reprocess

`src/application/review/reprocessing.py` và `actions.py` tạo `post_approval_run`, chạy ingestion/replay rồi reconciliation. Raw staged pages được materialize theo `raw_stage_key`; page đã consume/replay được đánh dấu idempotent. Runtime progress truy vấn qua review packet API và dashboard Review Center.

## 7. Dashboard/Copilot

Dashboard request đi qua typed clients trong `frontend-next/src/lib/api/` đến các router FastAPI. Copilot context ở `src/application/copilot/context.py` gom runtime, review packet, mapping, file và reconciliation evidence; action chỉ được thực hiện qua API approval contract.

## Persistence summary

| Dữ liệu | Store | Adapter |
|---|---|---|
| Config, checkpoint, runtime, review, audit, raw-page metadata | MongoDB | `src/infrastructure/*/repository.py` |
| Raw payload lớn | MongoDB GridFS | `raw_page_repository.py` |
| Partner/internal transaction và result | PostgreSQL | `src/infrastructure/postgres/`, `partner_transaction/` |
| Schema/index | Alembic + repository schema | `alembic/versions/`, `src/infrastructure/persistence/` |
