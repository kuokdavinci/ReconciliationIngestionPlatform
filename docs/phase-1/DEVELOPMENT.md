# Development

**Cập nhật:** 2026-08-27

## Prerequisites và cài đặt

- Python 3.11+, `uv`, Node.js và Docker Compose.

```bash
uv sync --all-extras --dev
cp .env.example .env
docker compose up -d postgres mongodb sftp mongo-express
uv run alembic upgrade head
```

`mongo-express` chỉ dành cho local. PostgreSQL là nguồn lưu transaction/result; MongoDB giữ config, metadata, workflow state và raw payload.

## Chạy ứng dụng

Backend:

```bash
uv run python run.py --serve --port 8000
# hoặc
uv run uvicorn src.api:create_app --factory --host 0.0.0.0 --port 8000
```

Frontend:

```bash
npm --prefix frontend-next ci
npm --prefix frontend-next run dev
```

Ingestion production chạy qua Airflow-backed API:

```bash
curl -X POST http://localhost:8000/api/v1/automation/jobs/MOMO/run \
  -H 'X-Actor: operator'
curl http://localhost:8000/api/v1/automation/jobs
```

Reconciliation thủ công:

```bash
uv run python run.py --reconcile 2024-07-07 --partner MOMO
```

Không dùng `run.py --data/--config` cho flow vận hành hiện tại; hai flag này còn tồn tại trong CLI nhưng composition repository của local-file path chưa được hoàn thiện. Xem [Known Issues](../KNOWN_ISSUES.md).

## Tests và quality gates

```bash
uv run ruff check src dags scripts cli
uv run mypy src --show-error-codes --no-incremental --check-untyped-defs
uv run pytest tests/ --ignore=tests/test_analysis_e2e.py

npm --prefix frontend-next run lint
npm --prefix frontend-next run typecheck
npm --prefix frontend-next run build
npm --prefix frontend-next run test:e2e
```

Real LLM E2E cần `AI_API_KEY` và chạy riêng:

```bash
uv run pytest tests/test_analysis_e2e.py --e2e -v
```

Test quan trọng nằm ở `tests/test_reconciliation_engine.py`, `test_reconciliation_keys.py`, `test_manual_reconciliation_service.py`, `test_ingestion_pipeline.py`, `test_ingestion_integration.py`, `test_api_reconciliation.py`, `test_api_review_packets.py` và các `test_analysis_*.py`.

## Make và demo

```bash
make ci
make test-quick
make momo-e2e-help
make momo-e2e-reset
make momo-e2e-run
make zalopay-e2e-reset
```

Các target đầy đủ nằm trong `Makefile`; seed/demo ở `scripts/demo/` và `scripts/seeding/`.

## Khi thay đổi cấu trúc

1. Sửa code/test theo boundary hiện tại.
2. Chạy `codegraph sync .` và `codegraph status`.
3. Chạy quality gates và `git diff --check`.
4. Đồng bộ README, [module map](MODULES.md), [architecture](ARCHITECTURE.md), [CI map](../CI-MAP.md) nếu public surface thay đổi.
