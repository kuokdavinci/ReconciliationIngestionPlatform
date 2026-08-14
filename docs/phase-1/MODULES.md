# Module Map

**Cập nhật:** 2026-08-14

Bản đồ dưới đây phản ánh package hiện có trong `src/`, `dags/` và `frontend-next/src/`. Không còn `src/scheduler/`, `src/services/` hoặc dashboard `frontend/` trong codegraph hiện tại.

## Backend

| Package | Trách nhiệm | Entry points / file tiêu biểu |
|---|---|---|
| `src/api/` | FastAPI routers và delivery contracts | `__init__.py`, `automation.py`, `review_packets.py`, `reconciliation.py` |
| `src/application/automation/` | Stream execution, job command/query, checkpoint wiring, backfill, Airflow contracts | `service.py::execute_stream`, `stream_runner.py::run_source_stream`, `stream_identity.py`, `backfill_service.py` |
| `src/application/ingestion/` | Source-unit orchestration, error classification, recovery view | `source_unit_orchestrator.py::process_source_units`, `recovery_view.py` |
| `src/application/review/` | Review packet, evidence, raw stream, validation, mapping approval/reprocess | `actions.py`, `mapping_workflow.py`, `raw_stream.py`, `runtime_validation.py` |
| `src/application/reconciliation/` | Manual reconciliation use cases và context queries | `service.py`, `manual_runs.py`, `queries.py` |
| `src/application/mapping/` | Mapping proposal, save/approve/reject và validation | `service.py`, `proposals.py`, `errors.py` |
| `src/application/runtime/` | Tạo/cập nhật/serialize runtime run | `service.py` |
| `src/domain/` | Domain models, ports và state contracts | `ingestion/`, `runtime/`, `review/`, `mapping/`, `reconciliation/` |
| `src/infrastructure/` | Mongo/PostgreSQL repositories, mappers, composition và workflow gateways | `persistence/`, `postgres/`, `workflows/airflow.py` |
| `src/pipeline/` | File-level và row-level ingestion | `ingestion_pipeline.py`, `row_pipeline.py`, `batch_writer.py`, `file_claim.py` |
| `src/fetchers/` | Partner input adapters | `api_fetcher.py`, `filedrop_fetcher.py`, `sftp_fetcher.py`, `base.py` |
| `src/readers/` | CSV, JSON, Excel readers | `csv_reader.py`, `json_reader.py`, `excel_reader.py` |
| `src/normalizer/` | Raw row → canonical value | `normalizer.py` |
| `src/validators/` | Canonical transaction validation | `validator.py` |
| `src/reconciliation/` | Key normalization, scope classification, matching engine | `keys.py`, `scope.py`, `engine.py` |
| `src/analysis/` | Insights, metrics, reports, alerts, guardrails, provider fallback | `provider.py`, `insights.py`, `services.py`, `guardrails.py` |
| `src/config/` | Settings, mapping loader/cache/validator, config health, AI mapping | `settings.py`, `loader.py`, `validator.py`, `config_health.py` |
| `src/core/` | Shared enums, constants, business date, canonical types | `enums.py`, `types.py`, `business_day.py` |
| `src/models/` | Compatibility/persistence models và index facades | `fetch_config.py`, `review_packet.py`, `partner_runtime_run.py`, `postgres.py` |
| `src/logging/` | Structured logging helpers | `logger.py` |

## Airflow và runtime entrypoints

| File | Vai trò |
|---|---|
| `run.py` | CLI dispatch cho `--serve`, ingestion và reconciliation |
| `api/server.py` | Uvicorn server wrapper |
| `backend/app.py` | Compatibility export của `create_app` |
| `dags/reconciliation_ingestion.py` | Airflow DAG `reconciliation_ingestion`, select streams và mapped run |
| `src/infrastructure/workflows/airflow.py` | Airflow REST gateway |
| `src/application/automation/contracts.py` | `ExecuteStreamCommand`, `ExecuteStreamResult`, outcome contract |

## API router map

| File | Prefix | Nghiệp vụ |
|---|---|---|
| `insights.py` | `/api/v1` | Insights và daily reports |
| `reconciliation.py` | `/api/v1/reconciliation` | Results, stats, runs, review records |
| `data_explorer.py` | `/api/v1/data` | Transactions, files, stats |
| `mappings.py` | `/api/v1/mappings`, `/api/v1/mapping` | Mapping CRUD, validate, publish, generate |
| `copilot.py` | `/api/v1/copilot` | Context và action approval |
| `operations.py` | `/api/v1/operations` | Intake/ingestion operations |
| `review_packets.py` | `/api/v1/review-packets` | Review, evidence, scope, approval/reprocess |
| `automation.py` | `/api/v1/automation` | Jobs, Run Now, retry, recovery, backfill |
| `audit.py` | `/api/v1/audit` | Audit events |

## Frontend

`frontend-next/src/` dùng App Router và chia theo feature:

- `app/`: `reconciliation`, `review-center`, `mapping-studio`, `schedules`, `audit-log` và home.
- `components/`: `layout`, `ui`, `reconciliation`, `review-center`, `mapping-studio`, `schedules`, `audit`.
- `lib/api/`: typed clients cho automation, review center, mapping, reconciliation và audit.
- `lib/state/`: stores và mock data cho UI.
- `types/`: API/domain types.

## Tests và scripts

- `tests/`: unit, architecture contract, API, integration, evaluation và E2E.
- `scripts/demo/`: demo scenario MOMO, ViettelPay, VNPAY và ZaloPay.
- `scripts/seeding/`: seed database/dataset.
- `scripts/tools/`: inspect/generate/check helpers.
- `scripts/*benchmark.py`: benchmark reconcile và reproducibility.
