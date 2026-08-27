# Data Flow hiện tại

**Cập nhật:** 2026-08-27

## Ingestion

```text
FileDrop / API / SFTP
  -> fetcher + source-unit identity
  -> claim file/unit
  -> mapping -> reader -> normalize -> validate/quarantine
  -> ingestion_key -> batch write PostgreSQL
  -> checkpoint/runtime metrics
```

Điểm thực thi chính:

- Fetch: `src/fetchers/` và `src/readers/`.
- Điều phối: `src/application/automation/stream_runner.py` và `src/application/ingestion/source_unit_orchestrator.py`.
- File/row pipeline: `src/pipeline/ingestion_pipeline.py`, `row_pipeline.py`.
- Persistence: `src/infrastructure/ingestion/` và `partner_transaction/`.

`source_unit_orchestrator` chỉ advance checkpoint sau khi persist thành công. File hash, fetch-unit key và `ingestion_key` bảo vệ retry/replay khỏi duplicate. API pagination có thể stage raw pages trong MongoDB GridFS để chờ review.

## Recovery và approval

```text
runtime failure / mapping drift
  -> review_packet + evidence
  -> runtime validation / draft mapping
  -> approve | keep-current | reject | send-to-studio
  -> replay staged pages hoặc source file
  -> ingestion -> reconciliation
```

Runtime/recovery: `src/application/runtime/service.py`, `recovery_view.py`, checkpoint/raw-page repositories. Review workflow: `src/application/review/actions.py`, `mapping_workflow.py`, `reprocessing.py` và `src/application/mapping/`.

## Reconciliation

Entry points:

- `run.py --reconcile YYYY-MM-DD --partner PARTNER`.
- `POST /api/v1/reconciliation/run`.
- Airflow stream sau ingestion.

```text
business date + partner
  -> đọc partner/internal transactions từ PostgreSQL
  -> normalize key + classify scope
  -> match amount/status
  -> batch write reconciliation_result
  -> stats/results/review/insight API
```

Code tương ứng: `src/application/reconciliation/manual_runs.py`, `queries.py`, `src/reconciliation/engine.py`, `keys.py`, `scope.py` và `src/infrastructure/reconciliation/`.

## Airflow control plane

```text
reconciliation_ingestion
  -> select_streams
  -> mapped run_stream
  -> execute_stream()
  -> run_source_stream()
  -> fetch / ingest / checkpoint / reconcile
```

DAG sở hữu schedule, dependency, retry/timeout và task log. Application sở hữu business state, checkpoint, source-unit retry và idempotency. Gateway là `src/infrastructure/workflows/airflow.py`; pilot hiện manual-only với `AIRFLOW_GLOBAL_SCHEDULE=none` và `AIRFLOW_TASK_RETRIES=0`.

## Data ownership

| Dữ liệu | Store |
|---|---|
| Partner/internal transactions, reconciliation results | PostgreSQL |
| Mapping/fetch config, file metadata, checkpoint, runtime, review, backfill, audit | MongoDB |
| Raw page payload lớn | MongoDB GridFS |
| Airflow metadata | PostgreSQL database `airflow` riêng |

Dashboard dùng typed clients trong `frontend-next/src/lib/api/` và gọi các router FastAPI; không đọc database trực tiếp.

## Phase 2: quality, quarantine và recovery

Sprint 3 mở rộng ingestion bằng các quyết định bounded, deterministic:

```text
file quality gate
  -> normalize source row -> validate canonical row
  -> duplicate classification -> batch persistence
      ├─ valid/new       -> PostgreSQL -> checkpoint advance
      ├─ row reject      -> quarantine -> valid rows vẫn tiếp tục
      ├─ equivalent dup  -> count/skip, không quarantine
      ├─ conflict dup    -> quarantine fingerprint -> HOLD_FOR_REVIEW
      └─ BATCH_FATAL      -> fail trước khi ghi row
```

Quarantine có lifecycle `PENDING → REPROCESSING → PENDING|RESOLVED|REJECTED`. Operator claim có lease/actor check; resolve, accept-existing, reject và escalate đều có audit/idempotency. Source unit chỉ resume khi blocker active đã terminal; checkpoint advance trước cleanup raw/file.

Các contract chính nằm ở `src/domain/ingestion/quality.py`, `quarantine.py`, `src/application/ingestion/quality_policy.py`, `quarantine_service.py`, `quarantine_reprocessing.py`, `source_unit_resume.py`, `src/pipeline/quality_gate.py` và `src/api/quarantine.py`.

Phase 2 cũng giữ rõ các boundary sau: API stream stage raw pages trong GridFS trước full-stream review/replay; Airflow chỉ sở hữu task orchestration; application sở hữu checkpoint/idempotency; backfill dùng parent `backfillRunId`; `WAITING_REVIEW` là business gate, không phải task failure.
