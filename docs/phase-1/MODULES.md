# Module Map

**Cập nhật:** 2026-08-27

Bản đồ này bám theo package và symbol trong CodeGraph hiện tại.

## Backend

| Package | Trách nhiệm | File/symbol chính |
|---|---|---|
| `src/api/` | FastAPI routers và delivery contract | `create_app`, `automation.py`, `review_packets.py`, `reconciliation.py` |
| `src/application/automation/` | Stream execution, checkpoint wiring, backfill, job commands | `service.py::execute_stream`, `stream_runner.py`, `backfill_service.py` |
| `src/application/ingestion/` | Quality/quarantine, source-unit sequencing, claim, retry, checkpoint, recovery view | `quality_policy.py`, `quarantine_service.py`, `source_unit_orchestrator.py`, `source_unit_resume.py` |
| `src/application/review/` | Evidence, raw stream, runtime validation, approval/reprocess | `actions.py`, `mapping_workflow.py`, `reprocessing.py` |
| `src/application/reconciliation/` | Manual reconciliation và context query | `manual_runs.py`, `queries.py` |
| `src/application/mapping/` | Mapping proposal, save/approve/reject, validation | `service.py`, `proposals.py`, `errors.py` |
| `src/application/runtime/` | Runtime run state và serialization | `service.py` |
| `src/domain/` | Models, ports, enums và state contracts | `ingestion/`, `runtime/`, `review/`, `reconciliation/` |
| `src/infrastructure/` | Mongo/PostgreSQL repositories và Airflow gateway | `persistence/`, `postgres/`, `workflows/airflow.py` |
| `src/pipeline/` | File/row processing, quality gate và batch write | `ingestion_pipeline.py`, `quality_gate.py`, `row_pipeline.py`, `batch_writer.py` |
| `src/fetchers/`, `src/readers/` | API/FileDrop/SFTP và CSV/JSON/Excel | `*_fetcher.py`, `*_reader.py` |
| `src/normalizer/`, `src/validators/` | Canonical value và transaction validation | `normalizer.py`, `validator.py` |
| `src/reconciliation/` | Key normalization, scope và matching engine | `keys.py`, `scope.py`, `engine.py` |
| `src/analysis/` | Metrics, insights, providers và guardrails | `metrics.py`, `insights.py`, `services.py` |
| `src/config/`, `src/core/` | Settings, mapping config, shared types/utilities | `settings.py`, `loader.py`, `utils.py` |

## Runtime surface

| Thành phần | Vai trò |
|---|---|
| `run.py` | `--serve` và `--reconcile`; ingestion production đi qua API/Airflow |
| `dags/reconciliation_ingestion.py` | `select_streams` và mapped `run_stream` |
| `src/infrastructure/workflows/airflow.py` | Airflow REST gateway |
| `frontend-next/src/app/` | 6 route App Router: home, reconciliation, review-center, mapping-studio, schedules, audit-log |

## API router map

| Router | Prefix |
|---|---|
| `insights.py` | `/api/v1` |
| `reconciliation.py` | `/api/v1/reconciliation` |
| `data_explorer.py` | `/api/v1/data` |
| `mappings.py` | `/api/v1/mappings`, `/api/v1/mapping` |
| `quarantine.py` | `/api/v1/quarantine` |
| `review_packets.py` | `/api/v1/review-packets` |
| `automation.py` | `/api/v1/automation` |
| `operations.py`, `copilot.py`, `audit.py` | `/api/v1/operations`, `/api/v1/copilot`, `/api/v1/audit` |

## Tests và tools

- `tests/`: unit, API/architecture contract, integration, evaluation và E2E.
- `scripts/demo/`, `scripts/seeding/`, `scripts/tools/`: demo, seed và inspection helpers.
- `alembic/`: PostgreSQL schema migrations; `docker/`: Compose/runtime notes.
