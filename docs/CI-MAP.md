# CI Map và Change Blast Radius

**Cập nhật:** 2026-08-14

Tài liệu này map thay đổi source → workflow kiểm chứng. Workflow thật nằm trong `.github/workflows/`; command dưới đây là local equivalent để chạy trước commit.

## Workflow overview

```mermaid
flowchart LR
    Change[Source change] --> Backend[Backend Quality]
    Change --> Ingestion[Ingestion Pipeline]
    Change --> Analysis[Analysis Eval]
    Change --> Frontend[Frontend CI]
    Backend --> B[Migration + Ruff + Mypy + backend tests]
    Ingestion --> I[Migration + ingestion tests + benchmark]
    Analysis --> A[Guardrails + providers + scenarios]
    Frontend --> F[ESLint + TypeScript + Webpack + Playwright]
```

## Workflow matrix

| Workflow | Trigger chính | Validation | Source scope |
|---|---|---|---|
| [Backend Quality](../.github/workflows/backend-quality.yml) | Push/PR `main`, manual | Alembic, Ruff, Mypy, backend tests | `src/`, `dags/`, `scripts/`, `cli/` |
| [Ingestion Pipeline](../.github/workflows/ingestion-pipeline.yml) | Push/PR `main`, manual | Alembic, ingestion lint, integration/pipeline/eval tests | `src/fetchers/`, `src/pipeline/`, `src/application/automation/`, ingestion models/repositories, demo scenarios |
| [Eval — AI Analysis Quality](../.github/workflows/eval.yml) | Push `main`/`feature/*`, PR, manual | Guardrails, provider fallback, scenario quality | `src/analysis/` và analysis API/services |
| [Frontend CI](../.github/workflows/frontend-ci.yml) | Push/PR, frontend paths, manual | ESLint, TypeScript, Webpack build, Playwright | `frontend-next/` |

Backend/Eval/Ingestion dùng Python 3.11, `uv sync --all-extras --dev` và PostgreSQL 16. Frontend CI dùng Node.js 22. Các test analysis yêu cầu `AI_API_KEY` fake; real LLM E2E được loại khỏi quality gate mặc định.

## Local commands

### Backend Quality

```bash
uv sync --all-extras --dev
uv run alembic upgrade head
uv run ruff check src dags scripts cli
uv run mypy src/ --show-error-codes
uv run pytest tests/ --ignore=tests/test_analysis_e2e.py --ignore=tests/test_ingestion_integration.py --ignore=tests/test_ingestion_pipeline.py --ignore=tests/test_seed_momo_e2e.py --ignore=tests/test_sprint1_eval_benchmark.py
```

### Ingestion Pipeline

```bash
uv run alembic upgrade head
uv run ruff check \
  src/fetchers \
  src/pipeline \
  src/application/automation \
  src/domain/fetch_config/models.py \
  src/infrastructure/persistence/mongo_indexes.py \
  scripts/demo/scenarios
uv run pytest \
  tests/test_indexes.py \
  tests/test_ingestion_integration.py \
  tests/test_ingestion_pipeline.py \
  tests/test_seed_momo_e2e.py \
  tests/test_sprint1_eval_benchmark.py \
  -v --tb=short
```

### Analysis Eval

```bash
AI_API_KEY=sk-test-fake-key uv run pytest tests/test_analysis_guardrails.py tests/test_analysis_providers.py tests/test_analysis_scenarios.py
AI_API_KEY=sk-test-fake-key uv run pytest tests/test_analysis_insights.py tests/test_analysis_services.py tests/test_analysis_schemas.py tests/test_analysis_metrics.py tests/test_analysis_grouping.py tests/test_analysis_alerter.py tests/test_analysis_reporter.py
```

### Frontend CI

```bash
npm --prefix frontend-next ci
npm --prefix frontend-next run lint
npm --prefix frontend-next run typecheck
npm --prefix frontend-next run build
npm --prefix frontend-next run playwright:install
npm --prefix frontend-next run test:e2e
```

## Blast-radius guide

| Thay đổi | Chạy trước | Kiểm tra thêm |
|---|---|---|
| `src/api/`, `src/config/` | Backend Quality | API contract, app factory, runtime callers |
| `src/application/automation/` | Backend Quality + Airflow tests | `tests/test_airflow_*.py`, automation/recovery/backfill tests, DAG payload |
| `src/application/ingestion/`, `src/pipeline/` | Ingestion Pipeline | checkpoint, raw staging, recovery view, backend tests |
| `src/fetchers/`, `src/domain/ingestion/` | Ingestion Pipeline | source-unit identity, retry/error classification, integration tests |
| `src/infrastructure/workflows/`, `dags/` | Airflow tests + `docker compose config --quiet` | Build Airflow image, DAG import, runtime correlation |
| `src/domain/`, `src/infrastructure/` | Workflow sở hữu adapter | repository, migration và API tests |
| `src/reconciliation/`, `src/application/reconciliation/` | Backend Quality | results, scope, review records, timezone/business-date tests |
| `src/analysis/` | Analysis Eval | Backend Quality nếu API/service contract thay đổi |
| `alembic/` | Backend + Ingestion | migration ordering, PostgreSQL integration |
| `frontend-next/` | Frontend CI | route navigation, API mocks, Playwright |

## Airflow-specific verification

Khi thay đổi DAG, gateway, orchestration contract hoặc Compose:

```bash
docker compose config --quiet
uv run pytest tests/test_airflow_deployment.py tests/test_airflow_runtime.py tests/test_airflow_backfill.py
docker compose build airflow-api-server
```

Live pilot cần bổ sung:

```bash
curl --fail http://localhost:8080/api/v2/monitor/health
docker compose exec airflow-api-server airflow dags list-import-errors
docker compose logs --tail 120 airflow-scheduler airflow-dag-processor
```

Acceptance phải chứng minh Run Now, page failure/resume, Retry now trong cùng `dagRunId`, review packet, ordered backfill và PostgreSQL row counts.

## Review sequence

1. Kiểm tra `codegraph status` và symbol/dependency của file đổi.
2. Chọn workflow theo bảng blast radius.
3. Chạy local equivalent và test contract liên quan.
4. Kiểm tra public API, layer ownership và runtime correlation.
5. Nếu thay đổi cấu trúc, chạy `codegraph sync .` rồi kiểm tra lại index.
