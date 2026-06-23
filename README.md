# Reconciliation Ingestion Platform

Config-driven platform for ingesting partner settlement files, normalizing into canonical transactions, matching against internal records via deterministic reconciliation, and managing mapping changes through human-in-the-loop approval workflows.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ · FastAPI 0.115+ · Uvicorn |
| Frontend | Next.js 16 · React 19 · TypeScript 5 · Tailwind CSS v4 |
| Database | MongoDB 7.0 via Motor 3.x (async driver) |
| AI/LLM | OpenAI-compatible API (direct HTTP, no LangChain) |
| Scheduling | APScheduler 3.x with MongoDB job store |
| File Parsing | openpyxl (Excel), csv, json — streaming readers |
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
  → DataContainerRepository.insert_many() (batch 100)
  → StructuredLogger events throughout
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

Key variables: `APP_MONGODB_URL`, `APP_DB_NAME`, `APP_LOG_LEVEL`, `AI_ENDPOINT`, `AI_MODEL`, `AI_API_KEY`.

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

`docker-compose.yml` defines: `mongodb`, `sftp`, `mongo-express`, `api`, `scheduler`.

See [docker/README.md](docker/README.md).

## Documentation Contract

This repo has historically drifted between docs and code. Treat code as source of truth:

- CLI behavior must match `run.py`
- Env vars must match `src/config/settings.py`, `src/analysis/config.py`, and `.env.example`
- API routes must match `src/api/`
- Frontend routes must match `frontend-next/src/app/`

If docs and code disagree, update docs or fix code in the same change.
