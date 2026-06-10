# Development

## Prerequisites

- Python `3.14+`
- `uv`
- Node.js
- Docker and Docker Compose

## Install

```bash
uv sync --all-extras
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

Relevant test areas currently present in the repo:

- readers and normalizer
- config cache, loader, validator, signature
- ingestion pipeline and ingestion integration
- reconciliation
- API routers
- automation endpoints
- review packet flows
- Copilot context
- analysis modules and E2E scenarios

## Directory Guide

- `src/`: backend code
- `frontend/`: dashboard
- `tests/`: automated tests
- `docs/`: project documentation
- `docker/`: Docker support files

## Known Documentation Rules

- Use `run.py` for CLI examples.
- Use router definitions in `src/api/` for endpoint references.
- Use settings classes and `.env.example` for environment variable references.
