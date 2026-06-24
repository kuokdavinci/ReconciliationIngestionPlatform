# Reconciliation Ingestion Platform

Config-driven platform for ingesting partner settlement files, normalizing into canonical transactions, matching against internal records via deterministic reconciliation, and managing mapping changes through human-in-the-loop approval workflows.

---

## Stack

| Layer | Technology |
|---|---|---|
| Backend | Python 3.11+ · FastAPI 0.115+ · Uvicorn |
| Frontend | Next.js 16 · React 19 · TypeScript 5 · Tailwind CSS v4 |
| Primary Database | MongoDB 7.0 via Motor 3.x (async driver) — configs, reviews, audit |
| Transactional Database | PostgreSQL 16 via asyncpg + SQLAlchemy — bulk ingestion, reconciliation |
| AI/LLM | OpenAI-compatible API (direct HTTP, no LangChain) |
| Scheduling | APScheduler 3.x with MongoDB job store |
| File Parsing | python-calamine (Excel), csv, json — streaming readers |
| Infrastructure | Docker · Docker Compose · SFTP (paramiko) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                     │
│  review-center · reconciliation · mapping-studio          │
│  schedules · audit-log                                    │
│  ┌────────────────────────────────────────────────────┐   │
│  │  lib/api/ · lib/state/ · components/ · types/       │   │
│  └────────────────────────────────────────────────────┘   │
└────────────────────────┬─────────────────────────────────┘
                         │ REST API (fetch) + X-Actor header
                         ▼
┌──────────────────────────────────────────────────────────┐
│                    FastAPI Backend                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ API      │ │ Services │ │ Pipeline │ │ Analysis    │  │
│  │ Routers  │ │ (audit,  │ │ (read →  │ │ (LLM       │  │
│  │ (11      │ │  review, │ │  normalize│ │  insights, │  │
│  │  groups) │ │  runtime) │ │  → validate│ │  guardrails)│  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Models   │ │ Config   │ │ Readers  │ │ Scheduler  │  │
│  │ (15+)    │ │ Loader   │ │ (CSV,    │ │ + Fetchers │  │
│  │ + Repos  │ │ + Cache  │ │  Excel,  │ │ (SFTP,     │  │
│  │          │ │ + Valid  │ │  JSON)   │ │  API, drop) │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘  │
└────────────────────────┬─────────────────────────────────┘
                         │ Motor (AsyncIO)
                         ▼
┌──────────────────────────────────────────────────────────┐
│                    MongoDB 7.0                             │
│  reconciliation_file · data_container · internal_txn      │
│  reconciliation_result · mapping_config · review_packet   │
│  copilot_action · audit_event · post_approval_run · ...   │
└──────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
src/                           # Python backend
├── core/                      # Shared enums, types, constants
├── config/                    # Settings, mapping config loader/cache/validator
├── models/                    # Pydantic models + MongoDB repositories
├── readers/                   # Streaming parsers (CSV, Excel, JSON)
├── normalizer/                # Field mapping → canonical transaction
├── validators/                # Business rule validation
├── pipeline/                  # Ingestion pipeline orchestrator
├── reconciliation/            # Transaction matching + scope classification
├── fetchers/                  # Partner data retrieval (SFTP, API, filedrop)
├── scheduler/                 # APScheduler job scheduling
├── analysis/                  # AI insight layer (LLM, guardrails, caching)
│   └── providers/             # LLM providers (OpenAI-compatible)
├── api/                       # FastAPI routers (11 groups)
├── services/                  # Cross-cutting helpers (audit, review, runtime)
└── logging/                   # Structured JSON logger

frontend-next/                 # Next.js dashboard
└── src/
    ├── app/                   # App Router pages
    │   ├── reconciliation/    # Reconciliation results + insights
    │   ├── review-center/     # Guided review + approval workflows
    │   ├── mapping-studio/    # Draft mapping wizard
    │   ├── schedules/         # Partner fetch schedule management
    │   └── audit-log/         # Audit event history
    ├── components/            # React components
    │   ├── ui/                # Shared design system (Button, Badge, Panel, Dialog)
    │   ├── layout/            # AppShell, Sidebar, Topbar
    │   ├── reconciliation/    # EvidenceTable, InsightGrid, SummaryStrip
    │   ├── review-center/     # GuidedReviewModal, step components
    │   ├── mapping-studio/    # MappingStudioWizard, ConfigsTable
    │   ├── schedules/         # ScheduleTable, RecentPacketsGrid
    │   └── audit/             # AuditTable, AuditDetailDialog
    ├── lib/                   # API client, state stores, normalizers
    │   ├── api/               # Typed HTTP modules per domain
    │   └── state/             # React hooks + mock data
    └── types/                 # TypeScript interfaces

tests/                         # pytest suite (48 test files)
├── conftest.py                # Shared fixtures + MongoDB mock
├── test_api_*.py              # API endpoint tests
├── test_analysis_*.py         # Analysis/LLM tests
├── test_reconciliation.py     # Engine tests
├── test_ingestion_*.py        # Pipeline + integration tests
└── test_*.py                  # Per-module unit tests
```

## Dashboard

`frontend-next/` is the active dashboard, built with Next.js and TypeScript.

Main active UI paths:

- `frontend-next/src/app/review-center/`
- `frontend-next/src/components/review-center/`
- `frontend-next/src/lib/api/review-center.ts`

The old `frontend/` Vite dashboard is kept only as a legacy/reference implementation.

---

## Key Data Flows

### Ingestion (file → canonical transactions)
```
run.py → IngestionPipeline.process_file()
  → dedup check (SHA256)
  → ConfigLoader.load() (cache-first, TTL 300s)
  → create_reader() → iter_rows()
  → TransactionNormalizer.normalize() (field mappings → typed values)
  → Validator.validate() (field presence, types, duplicates)
  → DataContainerRepository.insert_many() (configurable batch, default 20000)
  → StructuredLogger events throughout
  → PostgreSQL COPY (when enabled) via asyncpg copy_records_to_table
```

### Reconciliation (canonical → matched results)
```
ReconciliationEngine.reconcile(partner, date)
  → scope.classify_scope() (FULL_SNAPSHOT / INCREMENTAL_APPEND / REPLACEMENT)
  → query partner data_container + internal_transaction
  → _build_internal_index() (dedup by latest updated_at)
  → _iter_partner_record_batches() (batch 5000)
  → compare amount + status → ReconciliationStatus enum
  → batch write results (batch 5000), clear prior run
```

### Review & Approval
```
Review Packet Created (by upload / scheduler / mapping change)
  → Guided Review Modal (4 steps)
    1. Scope classification (LLM) + confirm
    2. Review draft mapping (AI-generated)
    3. Runtime validation (reprocess samples)
    4. Decision: Approve-Activate / Approve-Keep / Reject
  → PostApprovalRun (background re-ingestion + re-reconciliation)
```

---

## Quick Start

### Prerequisites

- Python 3.11+ with `uv`
- Docker + Docker Compose
- Node.js 20+

### Setup

```bash
# 1. Install backend dependencies
uv sync --all-extras

# 2. Configure environment
cp .env.example .env

# 3. Start infrastructure
docker compose up -d mongodb sftp mongo-express

# 4. Start API server
uv run python run.py --serve --port 8000

# 5. Start frontend (separate terminal)
npm --prefix frontend-next install
npm --prefix frontend-next run dev
```

### Open

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Mongo Express | http://localhost:8081 |

---

## CLI Commands

| Command | Description |
|---|---|
| `python run.py --serve` | Start API server |
| `python run.py --reconcile YYYY-MM-DD --partner MOMO` | Run reconciliation |
| `python run.py --reconcile YYYY-MM-DD --partner MOMO --seed-mock` | ...with mock internal data |
| `python run.py --data ./file.xlsx --partner MOMO --date 2024-07-07` | Run ingestion |
| `python run.py --config ./RequestTemplate.xlsx` | Upload mapping + SFTP fallback |
| `python run.py --start-scheduler` | Start scheduler daemon |
| `python run.py --run-job-now` | Trigger fetch job immediately |
| `python run.py --list-jobs` | List scheduled jobs |

## E2E Testing

The project includes end-to-end test suites for two partner integrations:

- **MOMO** — via `scripts/seeding/seed_momo_e2e.py` (wave-based phases, 20 records each)
- **ZALOPAY** — via `scripts/seeding/seed_zalopay_100k.py` (100k records)

### Seed Commands

```bash
# MOMO — Phase 1 (20 records)
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py reset

# MOMO — Phase 2 (add 20 records with new file)
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py phase2

# MOMO — Sprint 6 full setup
PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py sprint6-setup

# ZALOPAY — 100k records
PYTHONPATH=. uv run python scripts/seeding/seed_zalopay_100k.py reset
```

### Pytest E2E Tests (require `--e2e` flag + running services)

```bash
# 20 records test (MOMO + ZALOPAY)
uv run python -m pytest tests/test_e2e_20_records.py -v --e2e

# 100k records test (MOMO + ZALOPAY)
uv run python -m pytest tests/test_e2e_100k_records.py -v --e2e
```

### Makefile Shortcuts

```bash
make momo-e2e-reset         # Seed MOMO Phase 1
make momo-e2e-phase2        # Add MOMO Phase 2
make zalopay-e2e-reset      # Seed ZALOPAY 100k
make momo-e2e-run           # Trigger MOMO automation job
```

---

## Performance Benchmarks

100k-record ZALOPAY benchmark comparing three pipeline configurations:

| Configuration | Ingestion | Reconciliation | Ingestion (rec/s) | Reconciliation (rec/s) |
|---|---|---|---|---|
| **Baseline** (before optimizations) | 30.013s | 20.720s | 3,331 | 4,826 |
| **MongoDB Optimized** (calamine, fast-mode, parallel writes) | 14.359s | 13.436s | 6,916 | 7,342 |
| **Hybrid PostgreSQL** (UNLOGGED tables, SQL join reconciliation) | 12.555s | 4.577s | 7,964 | 22,160 |

### What Changed

| Optimization | Impact |
|---|---|
| Rust-backed `python-calamine` Excel parser (replaced openpyxl) | Excel load 15.5s → 1.07s (14.5x) |
| MongoDB bulk-write bypass of Pydantic (fast-mode) | Write CPU time reduced ~50% |
| PostgreSQL `UNLOGGED` tables for staging data | Ingestion DB write reduced 19% |
| PostgreSQL SQL `LEFT JOIN` in-database reconciliation | Reconciliation 13.4s → 4.6s (3x faster) |

Run benchmarks:

```bash
# MongoDB grid search (batch sizes, workers, ordered vs unordered)
uv run python scripts/parallel_benchmark.py

# 1M-row reconciliation benchmark
uv run python scripts/benchmark_reconcile_million.py

# Full trace report
cat docs/performance/INGEST_RECON_TRACE.md
```

---

## API Surface

The FastAPI app registers 11 router groups under `/api/v1/`:

| Router | Prefix | Key Endpoints |
|---|---|---|
| `insights` | `/api/v1` | `GET /insights/summary`, `/insights/discrepancies` |
| `reports` | `/api/v1/reports` | `GET /reports/daily` |
| `reconciliation` | `/api/v1/reconciliation` | `GET /results`, `/stats`, `/insights` |
| `data_explorer` | `/api/v1/data` | `GET /transactions`, `/files`, `/stats` |
| `mappings` | `/api/v1/mappings` | `GET /`, `POST /ai-generate` |
| `mapping` (v2) | `/api/v1/mapping` | `POST /ai-generate`, version CRUD |
| `copilot` | `/api/v1/copilot` | `GET /context`, `/actions` |
| `operations` | `/api/v1/operations` | `GET /intake`, partner ops |
| `review_packets` | `/api/v1/review-packets` | `GET /`, `POST /{id}/approve-activate` |
| `automation` | `/api/v1/automation` | `GET /jobs`, `POST /jobs/{partner}/run` |
| `audit` | `/api/v1/audit` | `GET /events` |

See `src/api/__init__.py` for router registration. Interactive docs at `/docs`.

---

## Configuration

Application settings loaded from `.env` with two config classes:

| Config | Prefix | Source |
|---|---|---|
| `Settings` | `APP_` | `src/config/settings.py` |
| `AnalysisConfig` | `AI_` | `src/analysis/config.py` |

Key variables: `APP_MONGODB_URL`, `APP_POSTGRES_URL`, `APP_DB_NAME`, `APP_LOG_LEVEL`, `AI_ENDPOINT`, `AI_MODEL`, `AI_API_KEY`.

Performance tuning variables: `APP_INGEST_BATCH_SIZE`, `APP_INGEST_WRITE_WORKERS`, `APP_RECON_PARTNER_BATCH_SIZE`, `APP_RECON_RESULT_BATCH_SIZE`, `APP_RECON_RESULT_WRITE_WORKERS`.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for full reference.

---

## Testing

```bash
# Run full suite
uv run python -m pytest -v

# Run specific module
uv run python -m pytest tests/test_api_review_packets.py -v

# With coverage
uv run python -m pytest --cov=src --cov-report=html
```

The test suite covers: ingestion pipeline, file readers, normalizer, validator, reconciliation engine, API routers, review packet flow, automation, analysis/insights, and end-to-end flows.

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Data Flow](docs/DATA_FLOW.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Module Map](docs/MODULES.md)

---

## Docker

`docker-compose.yml` defines: `mongodb`, `postgres`, `sftp`, `mongo-express`, `api`, `scheduler`.

See [docker/README.md](docker/README.md).

## Documentation Contract

This repo has historically drifted between docs and code. Treat code as source of truth:

- CLI behavior must match `run.py`
- Env vars must match `src/config/settings.py`, `src/analysis/config.py`, and `.env.example`
- API routes must match `src/api/`
- dashboard route descriptions must match `frontend-next/src/app/` and active Review Center components

If docs and code disagree, update docs or fix code in the same change.
