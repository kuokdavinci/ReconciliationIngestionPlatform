# Reconciliation Ingestion Platform

Config-driven platform for ingesting partner settlement data, normalizing canonical transactions, reconciling them against internal records, and operating the ingestion and review lifecycle.

The current repository combines the foundation system with Phase 2 ingestion-reliability work: Sprint 1 idempotency, Sprint 2 incremental recovery, Sprint 3 data quality/quarantine and Sprint 4 observability. Phase 1 documents remain foundation/reference material; the current reliability scope is documented in [docs/INDEX.md](docs/INDEX.md).

## Features

- CSV, JSON and Excel ingestion from filedrop, API or SFTP.
- Configurable mapping, normalization and validation.
- PostgreSQL transaction storage and deterministic reconciliation.
- File, fetch-unit and transaction idempotency with duplicate-safe retries.
- MongoDB-backed configuration, review packets, schedules and audit metadata.
- Next.js dashboard for reconciliation, review, mapping studio, schedules and audit history.

## Architecture

```text
Partner file/API/SFTP
        |
        v
Fetch + claim (fileHash/fetchUnitKey)
        |
        v
Read -> normalize -> validate -> derive ingestion_key
        |
        v
PostgreSQL: partner transactions, internal transactions, results
MongoDB: configs, file claims, review packets, schedules, audit metadata
        |
        v
FastAPI + Next.js dashboard
```

Transaction idempotency is enforced by PostgreSQL uniqueness on `(identify, ingestion_key)`. A replay is safe at both the claim boundary and the database boundary.

### Runtime components

| Layer | Responsibility | Main location |
|---|---|---|
| Fetchers | Filedrop, SFTP and API retrieval | `src/fetchers/` |
| Pipeline | Claims, reading, mapping, validation, key derivation and persistence | `src/pipeline/ingestion_pipeline.py` |
| Persistence | PostgreSQL transaction and MongoDB metadata repositories | `src/models/` |
| Scheduler | Partner jobs, fetch metadata and runtime outcomes | `src/scheduler/` |
| Reconciliation | Scope classification, matching and result persistence | `src/reconciliation/` |
| Review/runtime | Runtime validation, review packets and approvals | `src/services/`, `src/api/review_packets.py` |
| API | Operations, automation, reconciliation, review and audit endpoints | `src/api/` |
| Dashboard | Reconciliation, review, mapping, schedules and audit views | `frontend-next/src/` |

### Data ownership

| Store | Data |
|---|---|
| PostgreSQL | `partner_transaction`, `internal_transaction`, `reconciliation_result` |
| MongoDB | `reconciliation_file`, mapping/fetch configuration, review packets, audit events, schedules and runtime metadata |

PostgreSQL schema changes are managed through [Alembic](alembic/). Sprint 1 migration: [0002_ingestion_idempotency.py](alembic/versions/0002_ingestion_idempotency.py).

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn, SQLAlchemy/asyncpg |
| Frontend | Next.js 16, React 19, TypeScript 5 |
| Databases | PostgreSQL 16 and MongoDB 7 |
| Scheduling | APScheduler |
| Parsing | python-calamine, CSV and JSON readers |
| Infrastructure | Docker Compose, SFTP/Paramiko |

## Quick start

Prerequisites: Python 3.11+, `uv`, Node.js 20+ and Docker Compose.

```bash
uv sync --all-extras
cp .env.example .env
docker compose up -d mongodb postgres sftp mongo-express
uv run python run.py --serve --port 8000
```

In another terminal:

```bash
npm --prefix frontend-next install
npm --prefix frontend-next run dev
```

Dashboard: http://localhost:3000
API docs: http://localhost:8000/docs
Mongo Express: http://localhost:8082

## CLI and operational commands

| Command | Purpose |
|---|---|
| `uv run python run.py --serve` | Start FastAPI |
| `uv run python run.py --reconcile YYYY-MM-DD --partner MOMO` | Run reconciliation |
| `uv run python run.py --data ./file.xlsx --partner MOMO --date YYYY-MM-DD` | Ingest a file directly |
| `uv run python run.py --start-scheduler` | Start scheduler |
| `uv run python run.py --list-jobs` | List scheduled jobs |
| `uv run python run.py --run-job-now` | Trigger a job immediately |
| `make momo-e2e-reset` | Reset MOMO demo data |
| `make momo-e2e-phase2` | Prepare the 20-old + 10-new partial-duplicate demo |
| `make momo-e2e-run` | Trigger the MOMO automation job |
| `make test` | Run the project test target |

## Testing

```bash
uv run python -m pytest -v
UV_CACHE_DIR=$PWD/.uv-cache uv run python -m pytest tests/test_sprint1_eval_benchmark.py -q
npm --prefix frontend-next run lint
```

Full-stack E2E tests require running Docker services and the `--e2e` flag.

## Documentation

- [Documentation index](docs/INDEX.md)
- [Phase 2 roadmap and sprint plans](docs/MILESTONES.md)
- [Foundation architecture reference](docs/phase-1/ARCHITECTURE.md)
- [Configuration reference](docs/phase-1/CONFIGURATION.md)
- [Sprint 1 summary](docs/phase-2/sprint-1-summary.md)
- [Sprint 1 idempotency report](docs/phase-2/sprint-1-idempotency-report.md)
- [Sprint 1 benchmark specification](docs/phase-2/sprint-1-eval-benchmark.md)
- [Sprint 1 benchmark run](docs/phase-2/sprint-1-eval-benchmark-run.md)
- [Docker guide](docker/README.md)

## Configuration

Copy `.env.example` to `.env`. Application settings use the `APP_` prefix; AI settings use `AI_`. Important variables include `APP_MONGODB_URL`, `APP_POSTGRES_URL`, `APP_DB_NAME`, `AI_ENDPOINT`, `AI_MODEL` and `AI_API_KEY`.

See [`.env.example`](.env.example) and [src/config/settings.py](src/config/settings.py) for authoritative defaults.

## Repository layout

```text
src/                 Python application modules
frontend-next/       Next.js dashboard
scripts/              Seed, benchmark and utility scripts
tests/               Unit, integration and E2E tests
docs/                Architecture, sprint and operational docs
alembic/             PostgreSQL migrations
```

## Documentation contract

Phase 1 documents are foundation/reference material; Phase 2 documents describe current reliability work.

Code is the source of truth. CLI behavior must match `run.py` and `Makefile`; environment variables must match `src/config/settings.py` and `.env.example`; API descriptions must match `src/api/`; and dashboard descriptions must match `frontend-next/src/app/`. Update documentation when these contracts change.
