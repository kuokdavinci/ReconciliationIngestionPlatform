# Reconciliation Ingestion Platform

Nền tảng nhận settlement từ partner, chuẩn hóa/kiểm tra dữ liệu, đối soát với giao dịch nội bộ và hỗ trợ review–approval có audit.

Trạng thái hiện tại: FastAPI + Next.js, PostgreSQL cho dữ liệu đối soát, MongoDB cho metadata/config/workflow state và Airflow làm control plane.

## Kiến trúc hiện tại

```text
Partner (FileDrop / API / SFTP)
  -> fetcher -> source identity/claim -> read/normalize/validate
  -> PostgreSQL transaction tables
  -> checkpoint/runtime -> reconciliation engine -> PostgreSQL results
  -> Review Center / Mapping Studio / Audit
```

| Boundary | Trách nhiệm |
|---|---|
| `src/api/` | HTTP contract và response mapping |
| `src/application/` | Use case, orchestration, runtime/recovery, approval |
| `src/domain/` | Model, enum, port và business contract |
| `src/pipeline/`, `src/fetchers/`, `src/readers/` | Fetch, đọc file, normalize, validate, batch write |
| `src/infrastructure/` | PostgreSQL/MongoDB repositories và Airflow gateway |
| `dags/` | Schedule, dependency, retry/timeout và task state |

Không còn scheduler service riêng, `src/services/`, `src/models/` hay frontend cũ. Business logic chạy qua application; Airflow chỉ điều phối workflow.

## Data ownership

| Dữ liệu | Nguồn sự thật |
|---|---|
| `partner_transaction`, `internal_transaction`, `reconciliation_result` | PostgreSQL + Alembic |
| Mapping/fetch config, file metadata, checkpoint/source unit, runtime, review packet, backfill, audit | MongoDB |
| Raw page lớn | MongoDB GridFS |
| DAG/task metadata | Database `airflow` riêng trong PostgreSQL instance |

Idempotency dùng file hash, source-unit key, checkpoint và PostgreSQL `ingestion_key`/unique constraint. Business date dùng `APP_BUSINESS_TIMEZONE`; event timestamp trong PostgreSQL là UTC-naive.

## Entrypoints và product surface

- Backend: `run.py --serve` → `src.api:create_app`.
- Ingestion: Airflow DAG `reconciliation_ingestion` → `select_streams` → mapped `run_stream` → `execute_stream()`.
- Reconciliation: `run.py --reconcile DATE --partner PARTNER` hoặc `POST /api/v1/reconciliation/run`.
- Dashboard: `/`, `/reconciliation`, `/review-center`, `/mapping-studio`, `/schedules`, `/audit-log`.
- API groups: `/api/v1/reconciliation`, `/data`, `/mappings`, `/mapping`, `/review-packets`, `/automation`, `/operations`, `/insights`, `/copilot`, `/audit`.

## Chạy local

Yêu cầu Python 3.11+, `uv`, Node.js và Docker Compose.

```bash
uv sync --all-extras --dev
cp .env.example .env
docker compose up -d postgres mongodb sftp mongo-express
uv run alembic upgrade head
uv run python run.py --serve --port 8000
```

- API/OpenAPI: <http://localhost:8000/docs>
- Mongo Express: <http://localhost:8082>
- Dashboard:

```bash
npm --prefix frontend-next ci
npm --prefix frontend-next run dev
```

Dashboard chạy tại <http://localhost:3000> và proxy `/api/*` về backend. Airflow pilot dùng `AIRFLOW_GLOBAL_SCHEDULE=none`; xem [runbook Airflow](docs/phase-2/sprint-2.5-airflow-migration.md).

## Kiểm tra chất lượng

```bash
uv run ruff check src dags scripts cli
uv run mypy src --show-error-codes --no-incremental --check-untyped-defs
uv run pytest tests/ --ignore=tests/test_analysis_e2e.py
npm --prefix frontend-next run lint
npm --prefix frontend-next run typecheck
npm --prefix frontend-next run build
```

Sau thay đổi cấu trúc, chạy `codegraph sync .` rồi kiểm tra `codegraph status`. Snapshot CodeGraph đã kiểm tra ngày 2026-08-27: 456 files, 7.347 nodes, 19.126 edges, index up to date.

## Repository map

```text
src/{api,application,domain,infrastructure}  # backend boundaries
src/{pipeline,fetchers,readers,normalizer,validators}  # ingestion
src/reconciliation                         # matching và scope
src/analysis                                # metrics, insights, AI guardrails
frontend-next                               # active Next.js dashboard
dags                                        # Airflow DAG
alembic                                     # PostgreSQL migrations
tests, scripts, docker, docs                 # verification, tools, runtime và docs
```

## Tài liệu

- [Documentation index](docs/INDEX.md)
- [Architecture](docs/phase-1/ARCHITECTURE.md) · [Data flow](docs/phase-1/DATA_FLOW.md) · [Module map](docs/phase-1/MODULES.md)
- [Development](docs/phase-1/DEVELOPMENT.md) · [Configuration](docs/phase-1/CONFIGURATION.md)
- [Milestones](docs/MILESTONES.md) · [Known issues](docs/KNOWN_ISSUES.md) · [CI map](docs/CI-MAP.md)
- [Frontend guide](frontend-next/README.md) · [Docker services](docker/README.md)

README và docs phải được đối chiếu với CodeGraph, `src/config/settings.py`, `.env.example`, `src/api/`, `frontend-next/src/app/`, `docker-compose.yml` và `.github/workflows/` khi có thay đổi cấu trúc.
