# Reconciliation Ingestion Platform

Config-driven reconciliation platform for ingesting partner settlement files, normalizing them into a canonical model, reviewing mapping changes with human approval, and exposing operations/reconciliation workflows through FastAPI and a Next.js dashboard.

## What Is In This Repo

- Python backend under `src/` for ingestion, reconciliation, approvals, automation, and AI-assisted analysis
- CLI entrypoint in `run.py` for ingestion, reconciliation, scheduler control, and API serving
- Active Next.js dashboard in `frontend-next/`
- Legacy Vite dashboard in `frontend/` kept only as reference
- MongoDB-backed persistence for files, mappings, review packets, copilot actions, and reconciliation results

## Current Architecture

- `src/pipeline/`: file ingestion orchestration
- `src/reconciliation/`: deterministic reconciliation engine
- `src/api/`: FastAPI routers under `/api/v1/*`
- `src/config/`: runtime settings, mapping validation/loading, config health
- `src/models/`: MongoDB models, repositories, indexes
- `src/scheduler/` and `src/fetchers/`: scheduled partner fetch and automation jobs
- `src/analysis/`: AI-assisted insights layer
- `src/services/copilot_context.py`: dashboard Copilot context assembly

More detail:

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Data Flow](docs/DATA_FLOW.md)
- [Development](docs/DEVELOPMENT.md)
- [Module Map](docs/MODULES.md)

## Prerequisites

- Python `3.11+` for local development via `uv`
- `uv`
- Docker and Docker Compose for MongoDB/SFTP and optional full local stack
- Node.js for the dashboard

## Quick Start

1. Install Python dependencies:

```bash
uv sync --all-extras
```

2. Create environment file:

```bash
cp .env.example .env
```

3. Start supporting services:

```bash
docker compose up -d mongodb sftp mongo-express
```

`mongo-express` in `docker-compose.yml` is configured for local development convenience and currently runs with `ME_CONFIG_BASICAUTH: "false"`.
Do not expose it beyond localhost or reuse that setting as a production default.

4. Start the backend API:

```bash
uv run python run.py --serve --port 8000
```

5. Start the frontend:

```bash
npm --prefix frontend-next install
npm --prefix frontend-next run dev
```

6. Open:

- Dashboard: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- Mongo Express: `http://localhost:8081`

## CLI Workflows

The executable surface is defined by `run.py`.

Serve the API:

```bash
uv run python run.py --serve --port 8000
```

List scheduler jobs:

```bash
uv run python run.py --list-jobs
```

Start the scheduler daemon:

```bash
uv run python run.py --start-scheduler
```

Trigger the daily fetch job immediately:

```bash
uv run python run.py --run-job-now
```

Run ingestion against a local file:

```bash
uv run python run.py --data ./path/to/file.xlsx --partner MOMO --date 2024-07-07
```

Upload mapping config from an Excel template and ingest with SFTP/local fallback flow:

```bash
uv run python run.py --config ./path/to/RequestTemplate.xlsx
```

Run reconciliation:

```bash
uv run python run.py --reconcile 2024-07-07 --partner MOMO
```

Run reconciliation with seeded mock internal transactions:

```bash
uv run python run.py --reconcile 2024-07-07 --partner MOMO --seed-mock
```

## API Surface

The FastAPI app is created by `src.api:create_app` and currently includes these router groups:

- `/api/v1/insights/*`
- `/api/v1/reports/*`
- `/api/v1/reconciliation/*`
- `/api/v1/data/*`
- `/api/v1/mappings/*`
- `/api/v1/mapping/*`
- `/api/v1/copilot/*`
- `/api/v1/operations/*`
- `/api/v1/review-packets/*`
- `/api/v1/automation/*`

Representative endpoints:

- `GET /api/v1/insights/summary`
- `GET /api/v1/insights/discrepancies`
- `GET /api/v1/reports/daily`
- `GET /api/v1/reconciliation/results`
- `GET /api/v1/reconciliation/stats`
- `GET /api/v1/reconciliation/insights`
- `GET /api/v1/data/transactions`
- `GET /api/v1/data/files`
- `GET /api/v1/mappings`
- `POST /api/v1/mapping/ai-generate`
- `GET /api/v1/copilot/context`
- `GET /api/v1/operations/intake`
- `GET /api/v1/review-packets`
- `POST /api/v1/review-packets/{packet_id}/approve-activate`
- `POST /api/v1/review-packets/{packet_id}/approve-keep-current`
- `POST /api/v1/review-packets/{packet_id}/reject`
- `GET /api/v1/automation/jobs`
- `POST /api/v1/automation/jobs/{partner}/run`

Use `/docs` for the current request/response schema.

## Dashboard

`frontend-next/` is the active dashboard, built with Next.js and TypeScript.

Main active UI paths:

- `frontend-next/src/app/review-center/`
- `frontend-next/src/components/review-center/`
- `frontend-next/src/lib/api/review-center.ts`

The old `frontend/` Vite dashboard is kept only as a legacy/reference implementation.

## Configuration

Application settings are loaded from:

- `src/config/settings.py` with `APP_` prefix
- `src/analysis/config.py` with `AI_` prefix
- `.env`

Important variables:

- `APP_MONGODB_URL`
- `APP_DB_NAME`
- `APP_LOG_LEVEL`
- `APP_LOG_FORMAT`
- `APP_APP_NAME`
- `APP_STRICT_MAPPING_APPROVAL_ENABLED`
- `AI_PROVIDER`
- `AI_MODEL`
- `AI_ENDPOINT`
- `AI_API_KEY`
- `AI_FALLBACK_PROVIDER`
- `AI_FALLBACK_MODEL`
- `AI_TIMEOUT`

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Testing

Run the main suite:

```bash
uv run python -m pytest -v
```

Run a focused module:

```bash
uv run python -m pytest tests/test_api_review_packets.py -v
```

Run with coverage:

```bash
uv run python -m pytest --cov=src --cov-report=html
```

The repo currently includes tests for:

- ingestion pipeline and readers
- reconciliation
- API routers
- review packet flows
- automation run-now flows
- Copilot context
- analysis/insights modules

## Docker

`docker-compose.yml` currently defines:

- `mongodb`
- `sftp`
- `mongo-express`
- `api`
- `scheduler`

See [docker/README.md](docker/README.md).

## Documentation Contract

This repo has historically drifted between docs and code. Treat code as source of truth:

- CLI behavior must match `run.py`
- env vars must match `src/config/settings.py`, `src/analysis/config.py`, and `.env.example`
- API route docs must match `src/api/`
- dashboard route descriptions must match `frontend-next/src/app/` and active Review Center components

If docs and code disagree, update docs or fix code in the same change.
