# CI Map & Change Blast Radius

Tài liệu này mô tả cách thay đổi trong repository đi qua các workflow CI. Dùng nó để chọn đúng nhóm test trước khi commit hoặc review PR.

## Workflow overview

```mermaid
flowchart LR
    PR[Pull request to main] --> B[Backend Quality]
    PR --> I[Ingestion Pipeline]
    PUSH[Push to main or feature/*] --> E[Eval]
    PR --> E

    B --> B1[PostgreSQL 16 + Alembic]
    B --> B2[Ruff + Mypy]
    B --> B3[Backend tests]

    I --> I1[PostgreSQL 16 + Alembic]
    I --> I2[Ruff ingestion scope]
    I --> I3[Ingestion tests]

    E --> E1[Analysis guardrails]
    E --> E2[Provider fallback]
    E --> E3[Analysis scenarios]
    E --> E4[Analysis quality tests]

    PR --> F[Frontend CI]
    F --> F1[ESLint + TypeScript]
    F --> F2[Next.js production build]
    F --> F3[Playwright interaction smoke tests]
```

The backend, ingestion and analysis workflows use Python 3.11, `uv sync --all-extras --dev`, PostgreSQL 16 and `AI_API_KEY=sk-test-fake-key` where required. Frontend CI uses Node.js 22 and runs independently of backend services.

## Workflow matrix

| Workflow | Trigger | Main validation | Test scope | Main source areas |
|---|---|---|---|---|
| [Backend Quality](../.github/workflows/backend-quality.yml) | PR to `main`, manual | Alembic, Ruff, Mypy | All backend tests except E2E, ingestion integration/pipeline, MOMO E2E and Sprint 1 benchmark | `src/api/`, `src/config/`, `src/services/`, reconciliation and backend models |
| [Ingestion Pipeline](../.github/workflows/ingestion-pipeline.yml) | PR to `main`, manual | Alembic, ingestion Ruff | Index, ingestion integration/pipeline, MOMO E2E and Sprint 1 benchmark | `src/fetchers/`, `src/pipeline/`, `src/scheduler/`, ingestion services/models |
| [Eval — AI Analysis Quality](../.github/workflows/eval.yml) | Push to `main`/`feature/*`, PR to `main`, manual | Analysis behavior without a real LLM | Guardrails, providers, scenarios, insights, services, schemas, metrics, grouping, alerter and reporter | `src/analysis/`, related analysis APIs/services/schemas |
| [Frontend CI](../.github/workflows/frontend-ci.yml) | Push/PR to `main`, manual | ESLint, TypeScript, Next.js webpack build, Playwright | Dashboard route navigation and Mapping Studio interaction smoke tests | `frontend-next/` |

## Exact command map

### Backend Quality

```text
uv run alembic upgrade head
uv run ruff check src/api src/config src/models/audit_event.py
  src/models/indexes.py src/models/partner_runtime_run.py
  src/models/reconciliation_result.py src/reconciliation/engine.py
  src/services scripts/demo/scenarios/seed_vnpay_audit_flow.py
uv run mypy src/ --show-error-codes
uv run pytest tests/ \
  --ignore=tests/test_analysis_e2e.py \
  --ignore=tests/test_phase8.py \
  --ignore=tests/test_ingestion_integration.py \
  --ignore=tests/test_ingestion_pipeline.py \
  --ignore=tests/test_seed_momo_e2e.py \
  --ignore=tests/test_sprint1_eval_benchmark.py
```

### Ingestion Pipeline

```text
uv run alembic upgrade head
uv run ruff check src/fetchers src/pipeline src/scheduler src/services
  src/models/fetch_config.py src/models/indexes.py scripts/demo/scenarios
uv run pytest tests/test_indexes.py tests/test_ingestion_integration.py
  tests/test_ingestion_pipeline.py tests/test_seed_momo_e2e.py
  tests/test_sprint1_eval_benchmark.py
```

### Eval

```text
uv run pytest tests/test_analysis_guardrails.py
uv run pytest tests/test_analysis_providers.py
uv run pytest tests/test_analysis_scenarios.py
uv run pytest tests/test_analysis_insights.py tests/test_analysis_services.py
  tests/test_analysis_schemas.py tests/test_analysis_metrics.py
  tests/test_analysis_grouping.py tests/test_analysis_alerter.py
  tests/test_analysis_reporter.py
```

### Frontend CI

```text
npm --prefix frontend-next ci
npm --prefix frontend-next run lint
npm --prefix frontend-next exec tsc -- --noEmit
npm --prefix frontend-next run build -- --webpack
npm --prefix frontend-next exec playwright -- install --with-deps chromium
npm --prefix frontend-next run test:e2e
```

## Blast-radius guide

| Changed area | Run first | Also inspect |
|---|---|---|
| `src/api/`, `src/config/` | Backend Quality | API tests, compatibility facades and runtime callers |
| `src/services/`, `src/reconciliation/` | Backend Quality | Reconciliation/review tests and API response contracts |
| `src/pipeline/` | Ingestion Pipeline | Backend Quality if orchestration/runtime contracts changed |
| `src/fetchers/`, `src/scheduler/` | Ingestion Pipeline | Backend Quality for automation/job APIs |
| `src/models/fetch_config.py`, `src/models/indexes.py` | Both Backend Quality and Ingestion Pipeline | Domain/infrastructure facades and Mongo index tests |
| `src/domain/` or `src/infrastructure/` | Workflow owning its adapters | Legacy import paths, repository tests and related API tests |
| `src/analysis/` | Eval | Backend Quality because its general test command also includes analysis tests |
| `alembic/` | Backend Quality and Ingestion Pipeline | PostgreSQL integration behavior and migration ordering |
| `.github/workflows/` | The edited workflow | Its exact local command and YAML scope/exclusions |
| `frontend-next/` | Frontend CI | Run frontend lint, type check, webpack build and Playwright interaction tests |

## Change review sequence

```text
1. Identify changed symbols and imports with codegraph.
2. Map the changed path to the table above.
3. Run the owning workflow command locally.
4. Run dependent workflow commands when the change crosses a boundary.
5. Check compatibility facades and public API contracts.
6. Reindex codegraph after structural changes.
```

## Important CI boundaries

- Backend Quality intentionally excludes ingestion integration/pipeline tests; a backend-only green check does not prove the ingestion pipeline is healthy.
- Ingestion Pipeline covers the pipeline and benchmark path but does not replace the broader backend test suite.
- Eval validates analysis behavior separately and uses fake configuration; it does not verify production provider connectivity.
- Frontend CI runs browser interaction smoke tests with API requests mocked at the browser boundary, so it does not require a backend or database service.
- Codegraph provides structural dependency information. Workflow semantics, database state, Docker networking and environment-specific behavior still require CI/test verification.

## Maintenance rule

When adding or renaming a workflow, test group or major source boundary, update this file in the same change. The workflow YAML remains the executable source of truth; this map is the review and blast-radius guide.
