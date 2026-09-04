# CI Map và Change Blast Radius

**Cập nhật:** 2026-08-27

Tài liệu này map thay đổi source → workflow kiểm chứng. Workflow thật nằm trong `.github/workflows/`; command dưới đây là local equivalent để chạy trước commit.

## Tổng quan workflow

```mermaid
flowchart LR
    Change[PR / push / nightly] --> Selector[CI change detector]
    Selector --> Backend[Backend Quality]
    Selector --> Ingestion[Ingestion Pipeline]
    Selector --> Topology[Full Topology Contract]
    Selector --> Analysis[Analysis Eval]
    Selector --> Frontend[Frontend CI]
    Backend --> B[Migration + Ruff + Mypy + backend tests]
    Ingestion --> I[Migration + ingestion tests + benchmark]
    Topology --> T[Compose: API + Mongo + PostgreSQL + Airflow + source mock + SFTP]
    Analysis --> A[Guardrails + providers + scenarios]
    Frontend --> F[ESLint + TypeScript + Webpack + Playwright]
    B --> Gate[CI gate]
    I --> Gate
    T --> Gate
    A --> Gate
    F --> Gate
```

## Ma trận workflow

| Workflow | Trigger chính | Validation | Source scope |
|---|---|---|---|
| [CI entrypoint](../.github/workflows/ci.yml) | Push/PR `main`, nightly, manual | Change detection, reusable workflow dispatch, final `CI gate` | All scopes below |
| [Backend Quality](../.github/workflows/backend-quality.yml) | Called by CI when backend scope changes | Alembic, Ruff, Mypy, backend tests | `src/`, `dags/`, `scripts/`, `cli/`, tests |
| [Ingestion Pipeline](../.github/workflows/ingestion-pipeline.yml) | Called by CI when ingestion scope changes | Alembic, ingestion lint, integration/pipeline/eval tests | Fetchers, pipeline, automation and ingestion adapters |
| [Topology Contract](../.github/workflows/topology-contract.yml) | Called by CI for topology/runtime changes; nightly/manual | Compose startup plus API → Airflow → source → Mongo/PostgreSQL contract | `docker-compose.yml`, Airflow, automation, persistence, demo source |
| [Eval — AI Analysis Quality](../.github/workflows/eval.yml) | Called by CI when analysis scope changes | Guardrails, provider fallback, scenario quality | `src/analysis/` and analysis tests |
| [Frontend CI](../.github/workflows/frontend-ci.yml) | Called by CI when frontend scope changes | ESLint, TypeScript, Webpack build, Playwright | `frontend-next/` |

Backend/Eval/Ingestion dùng Python 3.11, `uv sync --all-extras --dev` và PostgreSQL 16. Frontend CI dùng Node.js 22. Các test analysis yêu cầu `AI_API_KEY` fake; real LLM E2E được loại khỏi quality gate mặc định.

`CI / CI gate` là check duy nhất cần đặt thành required status check trên branch protection. Scope không bị ảnh hưởng sẽ được skip ở job level và vẫn được tổng hợp thành trạng thái thành công; thay đổi workflow, dependency, Compose hoặc nightly/manual run sẽ mở toàn bộ scope.

## Các command local

### Backend Quality

```bash
uv sync --all-extras --dev
uv run alembic upgrade head
uv run ruff check src dags scripts cli
uv run mypy src --show-error-codes --no-incremental --check-untyped-defs
uv run mypy dags scripts cli --show-error-codes --no-incremental
uv run pytest tests/ --integration --ignore=tests/test_analysis_e2e.py --ignore=tests/test_ingestion_integration.py --ignore=tests/test_ingestion_pipeline.py --ignore=tests/test_seed_momo_e2e.py --ignore=tests/test_sprint1_eval_benchmark.py
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
  --integration \
  tests/test_indexes.py \
  tests/test_ingestion_integration.py \
  tests/test_ingestion_pipeline.py \
  tests/test_seed_momo_e2e.py \
  tests/test_sprint1_eval_benchmark.py \
  -v --tb=short
```

Local `pytest` runs skip real-service integration tests by default. Use
`pytest --integration -m integration` when PostgreSQL is reachable. Set
`TEST_POSTGRES_URL` to the network-specific URL when the test runner is inside
Compose, for example
`postgresql+asyncpg://postgres:postgres@postgres:5432/reconciliation`;
host runners normally use `localhost`.

### Workstream B — Quality contract and gate

```bash
uv run pytest \
  tests/test_quality_contract.py \
  tests/test_quality_profile.py \
  tests/test_benchmark_quality_contract.py \
  tests/test_ingestion_pipeline.py \
  -v --tb=short
uv run python scripts/benchmark_quality_contract.py \
  --sizes 10000,100000,1000000 \
  --repeats 1 \
  --output /tmp/workstream-b-quality-benchmark.json
```

Quality microbenchmark là evidence về CPU/memory, tách biệt với full-dataset
ingestion benchmark. Lệnh này có thể lâu hơn đáng kể so với focused contract
test vì đo ba scenario bằng `tracemalloc`.

### Workstream C — Normalization and validation

```bash
uv run pytest \
  tests/test_timestamp_normalization.py \
  tests/test_normalizer.py \
  tests/test_validator.py \
  tests/test_persistence_time.py \
  tests/test_persistence_mappers.py \
  tests/test_quality_contract.py \
  tests/test_ingestion_pipeline.py \
  tests/test_benchmark_fraud_detection.py \
  tests/test_benchmark_quality_contract.py \
  tests/test_api_review_packets.py::test_runtime_timestamp_code_does_not_parse_reason \
  tests/test_api_review_packets.py::test_run_runtime_validation_returns_high_risk_for_failed_validation \
  -v --tb=short
uv run python scripts/benchmark_fraud_detection.py --full-only
```

Focused C run hiện tại đã pass 242 test. Full-dataset command cần MongoDB/
PostgreSQL service chạy qua Docker và sẽ dọn benchmark record cùng temporary
mapping sau khi hoàn tất.

### Workstream D — Quarantine lifecycle

```bash
uv run ruff check src tests
uv run mypy src --show-error-codes --no-incremental --check-untyped-defs
uv run mypy dags scripts cli --show-error-codes --no-incremental
uv run pytest \
  tests/test_quarantine_domain.py \
  tests/test_quarantine_repository.py \
  tests/test_quarantine_reprocessing.py \
  tests/test_quarantine_service.py \
  tests/test_quarantine_source_unit.py \
  tests/test_quarantine_resume.py \
  tests/test_quarantine_retention.py \
  tests/test_api_quarantine.py \
  tests/test_quarantine_audit.py \
  tests/test_quarantine_lifecycle.py \
  tests/test_quarantine_runtime_wiring.py \
  tests/test_quarantine_adapters.py \
  tests/test_quarantine_source_unit_resume.py \
  -v --tb=short
```

Lifecycle gate bao phủ state transition, source-row replay/correction, duplicate
outcome, source-unit hold/resume, checkpoint ordering, API bound, audit metadata,
counter, retention evidence, runtime composition wiring, authoritative source
reader và fingerprint verification. Dùng Ingestion Pipeline workflow cho live
database và integration validation.

### Workstream E — Operator quarantine flow

```bash
uv run pytest \
  tests/test_quarantine_repository.py \
  tests/test_quarantine_lifecycle.py \
  tests/test_quarantine_service.py \
  tests/test_quarantine_actions.py \
  tests/test_quarantine_audit.py \
  tests/test_api_quarantine.py \
  tests/test_api_operations.py \
  tests/test_api_audit.py \
  -q --tb=short
```

Gate này kiểm tra explicit claim ownership, stale-status CAS, source-backed
resolution, accept-existing verification, yêu cầu reject reason, escalation
cap, idempotent action replay, audit action uniqueness, bounded queue summary,
stable error mapping và redaction. Đây là bounded local contract evidence.
Sprint 4 sở hữu notification, dashboard, stage metrics và observability mở rộng.

Local Review Center demo dùng cùng API namespace và deterministic fixture:

```bash
make quarantine-demo-reset
make quarantine-demo-run
make quarantine-demo-fatal-run
npm --prefix frontend-next run test:e2e -- e2e/quarantine-review.spec.ts --workers=1
npm --prefix frontend-next run test:e2e -- e2e/quarantine-demo-live.spec.ts --workers=1
```

Điều này chứng minh local UI wiring và bounded redaction trên mock data.
Command `DEMO1` là scenario file-quality-gate fatal trực tiếp.

### Analysis Eval

```bash
AI_API_KEY=sk-test-fake-key uv run pytest tests/test_analysis_guardrails.py tests/test_analysis_providers.py tests/test_analysis_scenarios.py
AI_API_KEY=sk-test-fake-key uv run pytest tests/test_analysis_insights.py tests/test_analysis_services.py tests/test_analysis_schemas.py tests/test_analysis_metrics.py tests/test_analysis_grouping.py tests/test_analysis_scenarios.py
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

## Hướng dẫn blast radius

| Thay đổi | Chạy trước | Kiểm tra thêm |
|---|---|---|
| `src/api/`, `src/config/` | Backend Quality | API contract, app factory, runtime callers |
| `src/domain/ingestion/quality.py`, `src/pipeline/quality_gate.py`, duplicate repository/fingerprint code | Workstream B gate + Ingestion Pipeline | quality contract, duplicate classification and bounded runtime result |
| `src/normalizer/`, `src/validators/`, persistence timestamp mappers, `scripts/benchmark_fraud_detection.py` | Workstream C gate + Ingestion Pipeline | normal/fast parity, UTC persistence mapping and full-dataset v2 benchmark |
| `src/application/automation/` | Backend Quality + Airflow tests | `tests/test_airflow_*.py`, automation/recovery/backfill tests, DAG payload |
| `src/application/ingestion/quarantine_*.py`, `src/api/quarantine.py`, `src/infrastructure/audit/` | Workstream D/E gate + Ingestion Pipeline | quarantine state/repository/API/audit/lifecycle tests, source-unit resume, ownership/CAS, queue summary and redaction tests |
| `src/application/ingestion/`, `src/pipeline/` | Ingestion Pipeline | checkpoint, raw staging, recovery view, backend tests |
| `src/fetchers/`, `src/domain/ingestion/` | Ingestion Pipeline | source-unit identity, retry/error classification, integration tests |
| `src/infrastructure/workflows/`, `dags/` | Airflow tests + `docker compose config --quiet` | Build Airflow image, DAG import, runtime correlation |
| `src/domain/`, `src/infrastructure/` | Workflow sở hữu adapter | repository, migration và API tests |
| `src/reconciliation/`, `src/application/reconciliation/` | Backend Quality | results, scope, review records, timezone/business-date tests |
| `src/analysis/` | Analysis Eval | Backend Quality nếu API/service contract thay đổi |
| `alembic/` | Backend + Ingestion | migration ordering, PostgreSQL integration |
| `frontend-next/` | Frontend CI | route navigation, API mocks, Playwright |

## Full topology contract

Contract test dùng đúng Compose topology thay vì mock repository:

```bash
cp .env.example .env
# Đặt các password local trong .env, sau đó:
docker compose up -d --build --wait \
  postgres mongodb sftp airflow-db-bootstrap airflow-volume-permissions \
  airflow-init airflow-api-server airflow-scheduler airflow-dag-processor \
  api viettelpay-mock
APP_MONGODB_URL='mongodb://admin:<password>@127.0.0.1:27017/reconciliation?authSource=admin' \
APP_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/reconciliation' \
uv run pytest tests/test_topology_contract.py --e2e -v --tb=short
docker compose down -v --remove-orphans
```

PR chỉ chạy contract này khi thay đổi chạm topology/runtime boundary. Nightly lúc
`02:17 UTC` và manual dispatch chạy full matrix để bắt drift giữa Compose services.

## Kiểm tra riêng cho Airflow

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

Acceptance phải chứng minh Run Now, page failure/resume, Retry now trong cùng
`dagRunId`, review packet, ordered backfill và PostgreSQL row counts.

## Trình tự review

1. Kiểm tra `codegraph status` và symbol/dependency của file đổi.
2. Chọn workflow theo bảng blast radius.
3. Chạy local equivalent và test contract liên quan.
4. Kiểm tra public API, layer ownership và runtime correlation.
5. Nếu thay đổi cấu trúc, chạy `codegraph sync .` rồi kiểm tra lại index.
