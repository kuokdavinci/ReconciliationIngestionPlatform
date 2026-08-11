# Development

**Cập nhật:** 2026-08-11

## Prerequisites

- Python `>=3.11` (xem `pyproject.toml`)
- Node.js (không có engines ràng buộc trong `frontend-next/package.json`)
- Docker và Docker Compose (cần cho MongoDB, PostgreSQL, SFTP)
- `uv` (recommended) hoặc `pip`

## Install

### Với uv (recommended)

```bash
uv sync --all-extras
cp .env.example .env
```

### Với pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

## Start Supporting Services

```bash
docker compose up -d mongodb postgres sftp mongo-express
```

`mongo-express` is a local/dev helper only.
Current Compose config disables its basic auth layer with `ME_CONFIG_BASICAUTH: "false"`, so keep it on localhost and do not mirror that posture outside development.

PostgreSQL (`postgres:16`) is used for bulk transactional processing (ingestion + reconciliation). Schema changes are applied through Alembic migrations in `alembic/versions/`; `src/models/postgres.py` provides the startup migration entrypoint.

### PostgreSQL Connection

Default connection: `postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation`

Configure via `APP_POSTGRES_URL` in `.env`.

## Run Backend

Preferred local command:

```bash
uv run python run.py --serve --port 8000
```

Direct Uvicorn also works:

```bash
uv run uvicorn src.api:create_app --factory --host 0.0.0.0 --port 8000
```

## Run Frontend

```bash
npm --prefix frontend-next install
npm --prefix frontend-next run dev
npm --prefix frontend-next run build
```

The frontend `build` script already selects the verified Webpack path (`next build --webpack`).

## Useful CLI Commands

List scheduler jobs:

```bash
uv run python run.py --list-jobs
```

Start scheduler:

```bash
uv run python run.py --start-scheduler
```

Trigger scheduler job now:

```bash
uv run python run.py --run-job-now
```

Run ingestion from a local file:

```bash
uv run python run.py --data ./path/to/file.xlsx --partner MOMO --date 2024-07-07
```

Run reconciliation:

```bash
uv run python run.py --reconcile 2024-07-07 --partner MOMO
```

## Makefile Targets

Dự án có `Makefile` với nhiều target tiện ích:

| Target | Mô tả |
|---|---|
| `make test` | Chạy all tests (trừ E2E và phase8) |
| `make test-quick` | Chạy nhanh, dừng ở lỗi đầu tiên (`-x --tb=short`) |
| `make test-analysis` | Chỉ chạy analysis tests |
| `make test-guardrails` | Chạy guardrail validation tests |
| `make test-eval` | Chạy eval scenarios (fallback, mixed_statuses) |
| `make eval-all` | Chạy toàn bộ eval suite (scenarios + guardrails + providers) |
| `make ci` | CI pipeline — tất cả tests trừ E2E |
| `make clean` | Dọn cache Python |

**MOMO E2E targets:**

| Target | Mô tả |
|---|---|
| `make momo-e2e-reset` | Reset seed data Phase 1 (20 rows) |
| `make momo-e2e-phase2` | Chuẩn bị partial-duplicate demo Phase 2 (20 rows cũ + 10 rows mới) |
| `make momo-e2e-phase2-full` | Legacy Phase 2: ghi file Wave 2 gồm 20 rows mới |
| `make momo-e2e-run` | Trigger MOMO automation job qua API |
| `make momo-e2e-job` | Kiểm tra trạng thái MOMO job |
| `make momo-e2e-rebuild` | Rebuild api + scheduler containers |
| `make momo-e2e-missing-partner-demo` | Inject MISSING_PARTNER row để test engine |
| `make momo-sprint6-setup` | Full cleanup + Sprint 6 dataset |
| `make momo-sprint6-wave2` | Activate Sprint 6 Wave 2 file |

**ZALOPAY E2E targets:**

| Target | Mô tả |
|---|---|
| `make zalopay-e2e-reset` | Seed 100k ZALOPAY records (internal + partner file + configs) |

## Tests

Run all tests:

```bash
uv run python -m pytest -v
```

Run a single test module:

```bash
uv run python -m pytest tests/test_api_review_packets.py -v
```

Run with coverage:

```bash
uv run python -m pytest --cov=src --cov-report=html
```

Run specific benchmark test:

```bash
uv run python -m pytest tests/test_api_reconciliation.py -v
```

### Relevant Test Areas

Các test modules hiện tại:

| File | Dòng | Mô tả |
|---|---|---|
| `tests/test_reconciliation.py` | — | Core reconciliation logic |
| `tests/test_api_review_packets.py` | — | Review packet API flows |
| `tests/test_api_reconciliation.py` | — | Reconciliation API endpoints |
| `tests/test_ingestion_pipeline.py` | – | Ingestion pipeline |
| `tests/test_ingestion_integration.py` | – | Ingestion integration |
| `tests/test_config_cache.py` | – | Config cache |
| `tests/test_config_loader.py` | – | Config loader |
| `tests/test_config_validator.py` | – | Config validator |
| `tests/test_config_signature.py` | – | Config signature |
| `tests/test_normalizer.py` | – | Normalizer |
| `tests/test_csv_reader.py`, `test_excel_reader.py`, `test_json_reader.py` | – | Readers |
| `tests/test_copilot_context.py` | – | Copilot context |
| `tests/test_api_automation*.py` | – | Automation endpoints |
| `tests/test_api_mapping*.py` | – | Mapping API |
| `tests/test_analysis_*.py` | – | Analysis modules (guardrails, scenarios, providers, etc.) |
| `tests/test_analysis_e2e.py`, `tests/test_phase8.py` | – | LLM E2E tests (--ignore trong make test) |
| `tests/test_seed_momo_e2e.py` | – | MOMO E2E seed helpers regression tests |
| `tests/test_e2e_20_records.py` | – | Full-stack E2E: 20 records MOMO + ZALOPAY (ingestion → reconciliation → verify) |
| `tests/test_e2e_100k_records.py` | – | Large volume E2E: 100k records MOMO + ZALOPAY (ingestion → reconciliation → verify) |

## Benchmarks

### Grid Search: Batch Size & Parallel Execution

Script `scripts/parallel_benchmark.py` thực hiện grid search trên ZALOPAY 100k records, test các tổ hợp batch size, worker count, và ordered/unordered inserts:

```bash
uv run python scripts/parallel_benchmark.py
```

Kết quả hiển thị matrix và đề xuất cấu hình tối ưu (xem [Performance Trace](performance/INGEST_RECON_TRACE.md)).

### 1M-Row Reconciliation Benchmark

```bash
uv run python scripts/benchmark_reconcile_million.py
```

Các tùy chọn:

```bash
# Bỏ qua seed (dùng data đã có)
uv run python scripts/benchmark_reconcile_million.py --skip-seed

# Kết nối Mongo URL tùy chỉnh
uv run python scripts/benchmark_reconcile_million.py --mongo-url "mongodb://admin:admin123@localhost:27017/reconciliation?authSource=admin"
```

### Performance Trace (3 Configurations)

So sánh Baseline ↔ MongoDB Optimized ↔ Hybrid PostgreSQL:

| Stage | Baseline | MongoDB Opt. | Hybrid PostgreSQL |
|---|---|---|---|
| Ingestion (100k) | 30.013s | 14.359s | **12.555s** |
| Reconciliation (100k) | 20.720s | 13.436s | **4.577s** |

Chi tiết: [docs/phase-1/performance/INGEST_RECON_TRACE.md](performance/INGEST_RECON_TRACE.md)

## E2E Testing với Seed Scripts

Demo seed scripts trong `scripts/demo/` dùng để tạo dữ liệu mẫu:

```bash
# Reset và seed MOMO E2E data (Phase 1)
PYTHONPATH=. python scripts/demo/sprint1/seed_momo_e2e.py reset

# Seed Phase 2
PYTHONPATH=. python scripts/demo/sprint1/seed_momo_e2e.py phase2

# Demo trường hợp missing partner
PYTHONPATH=. python scripts/demo/sprint1/seed_momo_e2e.py missing_partner_demo

# ZALOPAY 100k records
PYTHONPATH=. uv run python scripts/seeding/seed_zalopay_100k.py reset

# Quick helpers
uv run python scripts/tools/generate_test_data.py --help
```

Hoặc dùng Makefile shortcuts:

```bash
make momo-e2e-reset
make momo-e2e-phase2
make momo-e2e-run
make zalopay-e2e-reset
```

## Directory Guide

| Đường dẫn | Mô tả |
|---|---|
| `src/` | Backend Python code (FastAPI) |
| `frontend-next/` | Dashboard (Next.js) |
| `tests/` | Automated tests (pytest) |
| `docs/` | Project documentation |
| `docker/` | Docker support files |
| `scripts/` | Demo, seed, benchmark và utility scripts |
| `scripts/demo/` | Demo fixtures, evaluation và scenario seed scripts |
| `scripts/seeding/` | Seed dữ liệu nền và benchmark fixtures |
| `tasks/` | Báo cáo đánh giá (eval.md, REPORT.md) |
| `reports/` | Báo cáo xuất (daily/) |
| `mock_data/` | Dữ liệu mẫu cho testing |
| `test_data/` | Test data files |
| `sftp_data/` | SFTP settlement files |
| `.planning/` | Planning artifacts (phases, roadmap, STATE.md) |
| `downloads/`, `tmp_downloads/` | Thư mục tạm cho file tải về |

## Known Documentation Rules

- Use `run.py` for CLI examples.
- Use router definitions in `src/api/` for endpoint references.
- Use settings classes and `.env.example` for environment variable references.
- Use `uv run python ...` cho commands (uv sync là primary install method).
