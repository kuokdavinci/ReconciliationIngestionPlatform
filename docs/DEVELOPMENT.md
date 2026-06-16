# Development

**Cập nhật:** 2026-06-16

## Prerequisites

- Python `>=3.14` (xem `pyproject.toml`)
- Node.js (không có engines ràng buộc trong `frontend/package.json`)
- Docker và Docker Compose
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
docker compose up -d mongodb sftp mongo-express
```

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
cd frontend
npm install
npm run dev
```

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
| `make momo-e2e-phase2` | Thêm seed data Phase 2 (20 rows + partner file) |
| `make momo-e2e-run` | Trigger MOMO automation job qua API |
| `make momo-e2e-job` | Kiểm tra trạng thái MOMO job |
| `make momo-e2e-rebuild` | Rebuild api + scheduler containers |

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
| `tests/test_reconciliation.py` | 758 | Core reconciliation logic |
| `tests/test_api_review_packets.py` | 559 | Review packet API flows |
| `tests/test_api_reconciliation.py` | 203 | Reconciliation API endpoints |
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
| `tests/test_seed_momo_e2e.py` | – | MOMO E2E seed helpers |

## Benchmarks

Script benchmark reconciliation với 1 triệu rows:

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

Script chạy thông qua Makefile:

```bash
make test-eval        # Eval scenarios
make eval-all         # Full eval suite
```

Kết quả benchmark được ghi tại `tasks/eval.md`.

## E2E Testing với Seed Scripts

Scripts trong `scratch/` và `scripts/seeding/` dùng để tạo dữ liệu mẫu:

```bash
# Reset và seed MOMO E2E data (Phase 1)
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py reset

# Seed Phase 2
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py phase2

# Demo trường hợp missing partner
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py missing_partner_demo

# Quick helpers trong scratch/
uv run python scratch/seed_momo_green.py
uv run python scratch/register_vnpay_job.py
uv run python scratch/check_db.py
```

Hoặc dùng Makefile shortcuts:

```bash
make momo-e2e-reset
make momo-e2e-phase2
make momo-e2e-run
```

## Directory Guide

| Đường dẫn | Mô tả |
|---|---|
| `src/` | Backend Python code (FastAPI) |
| `frontend/` | Dashboard (Vite) |
| `tests/` | Automated tests (pytest) |
| `docs/` | Project documentation |
| `docker/` | Docker support files |
| `scripts/` | Utility scripts và benchmark tools |
| `scripts/seeding/` | Seed data generators cho E2E tests |
| `scratch/` | Scripts ad-hoc, thử nghiệm nhanh |
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
