# Reconciliation Ingestion Platform

A configurable reconciliation ingestion platform with a human-in-the-loop approval model. It reads partner settlement reports, normalizes heterogeneous transaction data into a canonical model, and persists them into MongoDB — all driven by dynamic configuration with zero hardcoded parsing logic. The platform features a full Operations Dashboard with Command Center, Data Intake, Review Queue, Reconciliation, and Mapping Studio — all sharing a central `review_packet` approval model.

## Quick Start & Flow

This platform processes reconciliation files via SFTP or local simulation, parses them dynamically using MappingConfigs, normalizes/validates, and saves them to MongoDB.

### 1. Setup Environment
```bash
# Install dependencies
uv sync --all-extras

# Configure environment variables
cp .env.example .env
```

### 2. Run the Services (MongoDB & SFTP)
Using Docker Compose:
```bash
docker compose up -d
```
*Note: Seeding configuration templates (like MOMO template) runs on Mongo initialization. If you need a clean db refresh, run `docker compose down -v && docker compose up -d`.*

### 3. Run Pipeline Ingestion & Scheduler CLI
You can execute the pipeline or start the automated scheduler daemon using `run.py`. When run, it connects to MongoDB, **automatically applies index recommendations**, and executes the requested command:
```bash
# A. MANUAL INGESTION
# Run with a dynamic Excel configuration template (e.g. RequestTemplate.xlsx)
uv run python run.py --config /path/to/RequestTemplate.xlsx

# Run with existing config seed in MongoDB (uses default MOMO config)
uv run python run.py

# B. SCHEDULER DAEMON & AUTOMATED JOBS
# Start the background scheduler daemon (processes cron jobs in real-time)
uv run python run.py --start-scheduler

# List all scheduled jobs and their next run times
uv run python run.py --list-jobs

# Manually trigger the daily fetch job immediately
uv run python run.py --run-job-now
```

### 3.1 Run Scheduler via Docker Compose
To run the scheduler in the background as a Docker container (highly recommended for local/production):
```bash
# Build and start all services (including the scheduler daemon)
docker compose up -d --build

# View real-time logs of the scheduler
docker logs -f reconciliation-scheduler
```

### 4. Transaction Reconciliation

Run the deterministic reconciliation engine to compare ingested partner data against internal system transactions:

```bash
# Seed mock internal transactions for testing
uv run python run.py --reconcile 2024-07-07 --partner MOMO --seed-mock

# Run reconciliation without seeding (uses existing internal_transaction data)
uv run python run.py --reconcile 2024-07-07 --partner MOMO

# Alternative syntax using subcommand style
uv run python run.py reconcile --date 2024-07-07 --partner MOMO
```

Results are stored in the `reconciliation_result` collection with statuses: `MATCHED`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `MULTIPLE_MISMATCH`, `MISSING_INTERNAL`, `MISSING_PARTNER`, `UNMAPPED_SKIPPED` (records skipped due to invalid normalized data).

### 5. AI Analysis Layer

Run the AI-powered analysis engine to generate actionable insights from reconciliation results. The layer uses OpenAI-compatible LLMs (GPT-4o default) to analyze mismatch patterns, detect operational issues, and produce daily reports — **without exposing raw transaction data** to the LLM.

```bash
# Start the FastAPI API server (default port 8000)
uv run python run.py serve

# Query AI insights via API
curl "http://localhost:8000/api/v1/insights/summary?partner=MOMO&date=2024-07-07"
curl "http://localhost:8000/api/v1/insights/discrepancies?partner=MOMO&date=2024-07-07&focus=operational"
curl "http://localhost:8000/api/v1/reports/daily?date=2024-07-07"
```

**Analysis Focus Types:**

| Focus | Use Case | Detects |
|-------|----------|---------|
| `operational` | Pipeline health | Missing internal/partner records, ingestion delays |
| `partner` | Partner behavior | Mismatch rate trends, volume anomalies, stability |
| `inconsistency` | Data quality | Amount mismatch clusters, status mismatch patterns |

**Design Principles:**
- **No raw data to LLM** — only aggregated metrics, grouped stats, and pre-processed anomalies
- **LLM fallback** — if LLM fails, returns rule-based insights only
- **Provider abstraction** — OpenAI-compatible (GPT-4o) default, Ollama deferred

### 6. Reconciliation & Data Explorer API

Read-only FastAPI endpoints for querying reconciliation results and browsing raw transaction data:

```bash
# Start the FastAPI server
uv run python run.py serve
```

**Reconciliation API** (`/api/v1/reconciliation`):

| Endpoint | Description |
|----------|-------------|
| `GET /results?partner=X&date=Y&status=Z&limit=N&offset=M` | Query reconciliation results with optional status filter and pagination |
| `GET /results/{id}` | Get single reconciliation result by partner transaction ID |
| `GET /insights?partner=X&date=Y&type=summary|anomalies|patterns|recommendations` | AI-powered reconciliation insights with 4 analysis focus types |
| `GET /stats?partner=X&date=Y` | Aggregated counts by status + total amounts |

**Data Explorer API** (`/api/v1/data`):

| Endpoint | Description |
|----------|-------------|
| `GET /transactions?partner=X&date=Y&trace=Z&status=W&amountMin=N&amountMax=M&dateFrom=D&dateTo=T` | Browse DataContainer records with optional filters (amount range, date range) and pagination |
| `GET /transactions/{id}` | Get single transaction by UUID |
| `GET /files?partner=X&date=Y&status=Z` | List reconciliation files with optional filters |
| `GET /files/{id}` | Get file detail with associated transaction count |
| `GET /stats?partner=X&date=Y` | Aggregate data volume statistics |

**Mapping Config API v2** (`/api/v1/mapping`):

| Endpoint | Description |
|----------|-------------|
| `POST /ai-generate?partner=X` | Upload sample spreadsheet — AI generates field mappings automatically |
| `POST /validate` | Validate mapping config rules (required fields, duplicate columns, empty sources) |
| `POST /test` | Test transformation of a sample row against a mapping config |
| `POST /publish` | Publish mapping config to MongoDB with version history snapshot |
| `GET /versions?partner=X` | List published config versions for a partner, sorted by date |
| `GET /version/{id}` | Get a specific version by ID from history collection |

### 6.1 Copilot API (/api/v1/copilot)

Embedded recommendation engine for the dashboard, providing contextual status, actions, and decision support per screen:

| Endpoint | Description |
|----------|-------------|
| `GET /context?partner=X&date=Y&screen=intake|review|reconciliation|automation` | Get contextual Copilot recommendation |
| `GET /context/file/{file_id}?partner=X&screen=...` | Get Copilot context for a specific file |
| `POST /actions/{action_key}` | Execute Copilot action |
| `GET /actions?status=X&partner=Y` | List Copilot action audit trail |
| `POST /actions/{action_id}/approve` | Legacy: Approve a Copilot action |
| `POST /actions/{action_id}/reject` | Legacy: Reject a Copilot action |

### 7. Operations Dashboard (Web UI)

A browser-based dashboard for monitoring and managing the platform:

```bash
# Terminal 1 — Start the FastAPI backend
uv run python run.py serve --port 8000

# Terminal 2 — Start the Vite frontend dev server
cd frontend
npm run dev
```

Then open `http://localhost:5173`.

**Dashboard Features:**

- **Command Center** — Top-level metrics, AI risk insight tabs (Operational / Partner Trends / Data Inconsistencies), action queue with severity-sorted anomalies, date/partner filtering
- **Data Intake** — Partner-level summary cards (ACTIVE / NEEDS_REVIEW / BLOCKED / NO_ACTIVITY), real-time file and config activity feed, pending review items with direct links to Review Queue / Approval Desk, active runtime config inspection
- **Review Queue** — Approval desk with full packet context: right-side drawer showing current runtime, parse strategy, validation gates (pass/warn/fail), sample preview rows. Three decision buttons: Approve & Activate Next Runtime, Approve Keep Current, Reject. Upload button to submit a file directly for review (creates proposal + packet + auto-routes here)
- **Reconciliation** — Deterministic mismatch review with status filter and pagination
- **Mapping Studio** — 3-step guided proposal workflow:
  1. **Choose Source** — Upload a partner sample spreadsheet (`.xlsx/.xls/.csv`) for AI auto-generation, upload an existing JSON schema, or paste a JSON template
  2. **Data Preview & AI Mapping** — Inspect detected file structure, tweak AI-proposed column mappings in the visual mapper or raw JSON editor, accept AI-suggested constants
  3. **Validation & Test** — Quality score with checklist (required fields, duplicate mappings, empty sources), run transformation tests on sample rows, browse version history. Proposal is saved as `PENDING_APPROVAL` and handed off to Review Queue
- **Automation** — Visibility into scheduled fetch configs, pending review packets per partner, Run Now (real execution — no fake toast), recent automation review output cards
- **AI Insights** — LLM-generated insights, discrepancy analysis, daily reports (accessible via API)
- **Settings** — Configure partner mappings and system settings

### 8. Running Tests
To run unit and integration tests:
```bash
uv run python -m pytest -v
```

To run end-to-end tests with real MongoDB and OpenAI API:
```bash
# Set environment variables (fish shell)
set -x E2E_MONGODB_URL "mongodb://admin:admin123@localhost:27017/reconciliation?authSource=admin"
set -x E2E_AI_API_KEY "sk-xxx"
set -x E2E_AI_MODEL "gpt-4o-mini"
set -x E2E_AI_ENDPOINT "https://api.openai.com/v1"
set -x E2E_DB_NAME "reconciliation"
uv run python -m pytest tests/test_analysis_e2e.py -v --e2e

# Or via bash
bash -c 'source .env && export E2E_MONGODB_URL="$APP_MONGODB_URL" E2E_AI_API_KEY="$AI_API_KEY" E2E_AI_MODEL="$AI_MODEL" E2E_AI_ENDPOINT="$AI_ENDPOINT" E2E_DB_NAME="$APP_DB_NAME" && uv run python -m pytest tests/test_analysis_e2e.py -v --e2e'
```

E2E tests verify: AI actually analyzes real data, detects operational issues, identifies amount mismatch patterns, handles clean data, follows JSON schema, differentiates focus types, respects privacy contract, and handles 1000+ transactions.

---

## MongoDB Indexes & Their Purpose

MongoDB indexes are defined in [indexes.py](file:///home/kuokdavinci/AdapterService/src/models/indexes.py) and applied **automatically on startup** in `run.py`.

* **`idx_file_hash_unique` (Unique index on `fileHash` in `reconciliation_file`)**:
  - *Purpose*: Prevents processing/ingesting the exact same file twice (idempotency/duplicate file prevention).
* **`idx_partner_date` (Compound index on `partner + reconciliationDate` in `reconciliation_file`)**:
  - *Purpose*: Optimizes lookups when querying reconciliation history/status by partner on a specific date.
* **`idx_partner_workflow_type` (Compound index on `partner + workflowType + fileType` in `reconciliation_mapping_config`)**:
  - *Purpose*: Ensures ultra-fast loading of mapping configurations for a specific partner's flow.
* **`idx_trace` (Index on `partnerData.trace` in `data_container`)**:
  - *Purpose*: Speeds up transaction reconciliation (matching transactions by transaction trace/ID).
* **`idx_identify_date` (Compound index on `identify + reconciliationDate` in `data_container`)**:
  - *Purpose*: Optimizes queries fetching all normalized transactions of a partner on a specific date.
* **`idx_operation_status` (Index on `operationStatus` in `data_container`)**:
  - *Purpose*: Facilitates filtering transactions based on validation status (`SUCCESS`, `FAILED`, etc.).
* **`idx_partner_status` (Index on `partnerData.status` in `data_container`)**:
  - *Purpose*: Speeds up queries searching by partner's original transaction status.
* **`idx_source_file` (Index on `sourceFileId` in `data_container`)**:
  - *Purpose*: Associates transaction rows back to their parent import file record (auditing/cleanups).
* **`idx_internal_partner_txn_id` (Index on `partnerTxnId` in `internal_transaction`)**:
  - *Purpose*: Speeds up reconciliation matching by reconciliation key lookup.
* **`idx_internal_partner_txn_time` (Compound index on `partner + transactionTime` in `internal_transaction`)**:
  - *Purpose*: Optimizes fetching internal records by partner and date range during reconciliation.
* **`idx_recon_partner_txn_id` (Index on `partnerTxnId` in `reconciliation_result`)**:
  - *Purpose*: Fast lookup for idempotent result writes (delete existing + re-insert).
* **`idx_recon_status` (Index on `reconciliationStatus` in `reconciliation_result`)**:
  - *Purpose*: Enables filtering/summarization by reconciliation status (MATCHED, MISMATCH, etc.).

## Architecture

```
                         ┌────────────────────────────────────────────┐
                         │           Operations Dashboard            │
                         │  (frontend/ — Vanilla JS SPA + Proxy)     │
                         │                                            │
                         │  Command Center · Data Intake              │
                         │  Review Queue · Reconciliation             │
                         │  Mapping Studio · Automation               │
                         └──────┬─────────────────────────────────────┘
                                │ HTTP /api/*
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│                     FastAPI Server (src/api/)                       │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  operations  │  │ review_      │  │  automation              │  │
│  │  /intake     │  │ packets/*    │  │  /jobs • /jobs/{p}/run   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘  │
│         │                 │                      │                  │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────┴───────────────┐  │
│  │  mappings    │  │  insights    │  │  reconciliation          │  │
│  │  /mappings   │  │  /insights   │  │  /reconciliation/results │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘  │
│         │                 │                      │                  │
│         └────────┬────────┘                      │                  │
│                  ▼                                ▼                  │
│         ┌────────────────┐           ┌──────────────────────┐      │
│         │  AI Analysis   │           │  ReconciliationEng   │      │
│         │  (insights)    │           │  (deterministic)     │      │
│         └───────┬────────┘           └──────────┬───────────┘      │
└─────────────────┼───────────────────────────────┼──────────────────┘
                  │                               │
                  ▼                               ▼
     ┌──────────────────────────────────────────────────────┐
     │                      MongoDB                          │
     │                                                        │
     │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
     │  │ data_        │  │ internal_    │  │reconciliation_│  │
     │  │ container    │  │ transaction  │  │  result      │  │
     │  ├──────────────┤  ├──────────────┤  ├──────────────┤  │
     │  │reconciliation│  │reconciliation│  │ mapping_config│  │
     │  │  _file       │  │_mapping_    │  │  (APPROVED /  │  │
     │  │              │  │ config      │  │  PENDING_     │  │
     │  │              │  │              │  │  APPROVAL)    │  │
     │  ├──────────────┤  ├──────────────┤  ├──────────────┤  │
     │  │ review_      │  │ copilot_    │  │ fetch_config  │  │
     │  │ packet       │  │ action      │  │              │  │
     │  └──────────────┘  └──────────────┘  └──────────────┘  │
     └────────────────────────────────────────────────────────┘
                           ▲
                           │
              ┌────────────┴─────────────────┐
              │        Config Health          │
              │  (src/config/config_health.py)│
              │                               │
              │  1. compute_signature()        │
              │  2. Detect stale config         │
              │  3. AI generate proposal        │
              │  4. Create ReviewPacket         │
              │  5. Pending approval            │
              └────────────────────────────────┘
                           ▲
                           │
              ┌────────────┴─────────────────┐
              │  Scheduler (APScheduler)      │
              │  (src/scheduler/jobs.py)      │
              │                               │
              │  • daily_partner_fetch_job    │
              │  • run_fetch_config_once      │
              │  • Triggers Config Health     │
              │    → creates ReviewPacket     │
              └────────────────────────────────┘

Ingestion Pipeline (existing, unchanged):
  ExcelStreamReader → TransactionNormalizer → Validator → DataContainerRepo
                    ↕
              ConfigLoader → MappingConfig (cached)
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.14 |
| Database | MongoDB + motor (async driver) |
| Excel | openpyxl (read-only/streaming mode) |
| Validation | pydantic v2 |
| Config | pydantic-settings (env prefix `APP_`) |
| Decimal | `Decimal` (never float for money) |
| Logging | Python stdlib `logging` with JSON formatter |
| Testing | pytest + pytest-asyncio |
| AI/LLM | httpx (OpenAI-compatible API), GPT-4o default |
| API | FastAPI + uvicorn |
| Scheduler | APScheduler (persistent, MongoDB-backed) |
| Frontend | Vanilla JS SPA (no build step) — served via `frontend/server.py` proxy |
| Proxy | Python `http.server` with `/api` reverse proxy to FastAPI |

## Key Features

- **Zero hardcoded parsers** — all column mapping, transformations, and status normalization are defined in MongoDB `MappingConfig` documents
- **Memory-efficient** — openpyxl read-only mode streams rows, constant memory regardless of file size
- **Duplicate prevention** — SHA256 file hash + composite key (identify + reconciliationDate + trace)
- **Batch insertion** — configurable batch size (default 100) for efficient MongoDB writes
- **Structured logging** — JSON output with 5 event types (FILE_STARTED, FILE_COMPLETED, FILE_FAILED, ROW_SUCCESS, ROW_FAILED)
- **Deterministic reconciliation** — matches partner transactions to internal records by `partnerTxnId`, classifies results into MATCHED / mismatch variants / MISSING, stores in `reconciliation_result`
- **Status normalization** — Vietnamese status strings (Thành công, Thất bại, Hoàn tiền) normalized to standard enums
- **Duplicate resolution** — latest `updatedAt` wins for multiple internal records with same `partnerTxnId`
- **Audit trail** — every record includes createdBy, createdDate, lastModifiedBy, lastModifiedDate
- **AI-powered analysis** — LLM generates actionable insights from reconciliation results (mismatch patterns, operational issues, daily reports) with privacy-by-design (no raw data sent to LLM)
- **Automated scheduling** — APScheduler daemon fetches partner files via SFTP on cron schedules, with persistent job state in MongoDB
- **FastAPI REST API** — serves AI insights, reconciliation results, data explorer, mapping config endpoints, and Mapping Studio v2
- **Operations Dashboard** — browser-based UI with Overview, Reconciliation, Mapping Configs, AI Insights, Mapping Studio tabs
- **Data flow guard** — ReconciliationEngine pre-checks each partner record for valid normalized data before processing; invalid records are skipped with structured warning logs and tracked in stats
- **AI config auto-generation** — upload partner sample files; AI infers field mappings, data types, constants, and status normalization rules automatically
- **Config health auto-detection** — file structure signatures (MD5 of headers + column count) detect stale configs; error rate > 20% triggers AI re-generation; low-confidence outputs are saved as `PENDING_REVIEW` for manual approval
- **Self-healing pipeline** — `IngestionPipeline` calls `check_and_refresh_config()` before each run and `record_config_run_health()` after, enabling automatic recovery from partner file format changes
- **Config version history** — every publish snapshots to `reconciliation_mapping_config_history` with version restore support from the dashboard
- **Multi-format raw signature reader** — `compute_signature()` reads CSV, TSV, XLSX, and JSON without a MappingConfig, enabling structure fingerprinting for any partner file
- **Graceful sheet fallback** — `ExcelStreamReader` falls back to the active/first sheet when the configured sheet name is missing, with a structured warning log
- **Central approval model** — `review_packet` collection is the single source of truth for all config-change approvals. Every config proposal creates a packet, whether triggered by upload, scheduler job, or config health drift
- **Right-side approval drawer** — Review Queue displays a detailed packet drawer with current context, parse strategy, validation gates, sample preview, and two distinct approve actions (activate-next-runtime vs keep-current-for-file)
- **Direct intake upload** — Uploading a file from Review Queue creates a `MappingConfig` proposal + `ReviewPacket` + `CopilotAction` atomically in a single transaction
- **Mapping Studio handoff** — "Open in Mapping Studio" sends packet/proposal context (headers, sample rows, config ID) so the operator can refine the AI-generated proposal before returning to approve
- **Automation visibility** — `GET /api/v1/automation/jobs` returns all enabled fetch configs with pending packet counts and recent packet status per partner
- **Automation Run Now** — triggers real `run_fetch_config_once()` execution; creates a `SCHEDULER_JOB`-source `ReviewPacket` if format drift is detected; results reflected immediately in automation and review queue views
- **`MappingConfigStatus` lifecycle** — configs transition through `PENDING_APPROVAL` → `APPROVED` (or `REJECTED`) → `SUPERSEDED` (when a newer config is approved). Superseded configs are preserved for audit
- **Data Intake partner state** — Each partner is computed as `ACTIVE`, `NEEDS_REVIEW`, `BLOCKED`, or `NO_ACTIVITY` based on approved configs, pending packets, and recent files

## Project Structure

```
src/
├── core/           # Canonical types, enums, constants (incl. ReconciliationStatus)
├── config/         # Settings, ConfigCache, ConfigValidator, ConfigLoader,
│                   # ConfigHealthService, StructureSignature, AI config generator
├── services/       # CopilotContextService for dashboard recommendations
│   └── copilot_context.py  # Context building, screen-aware recommendations
├── readers/        # ExcelStreamReader (openpyxl read-only), CSV reader, JSON reader
├── normalizer/     # TransactionNormalizer (dynamic field mapping)
├── validators/     # Validator (business rules + duplicate detection)
├── pipeline/       # IngestionPipeline (full orchestration)
├── reconciliation/ # ReconciliationEngine (match + classify, status normalization)
├── analysis/       # AI Analysis Layer (metrics, grouping, LLM prompts, insights)
│   ├── config.py       # AnalysisConfig (AI_ env prefix)
│   ├── provider.py     # LLMProvider Protocol + factory
│   ├── providers/      # OpenAICompatProvider, OllamaProvider (deferred)
│   ├── schemas.py      # Pydantic contracts (AnalysisInput, AnalysisResult, etc.)
│   ├── metrics.py      # MetricsService (single source of truth)
│   ├── grouping.py     # GroupingEngine (status, amount range, partner)
│   ├── prompts.py      # System + analysis prompt builders
│   ├── services.py     # Helpers (build_analysis_input, parse_llm_insights)
│   ├── insights.py     # Orchestration (get_summary, get_discrepancies)
│   ├── reporter.py     # DailyReporter (format only)
│   └── alerter.py      # ThresholdAlerter (check only)
├── api/            # FastAPI server (all endpoints)
│   ├── __init__.py     # App factory + lifespan
│   ├── insights.py     # AI insights endpoints (summary, discrepancies, reports)
│   ├── reconciliation.py  # Reconciliation results API (results, stats)
│   ├── data_explorer.py   # Data Explorer API (transactions, files, stats)
│   ├── mappings.py        # Mapping config API v1 & v2 (list, approve, save,
│   │                      # ai-generate, validate, test, publish, versions)
│   ├── review_packets.py  # Review packet approval endpoints
│   ├── copilot.py         # Copilot API (context, actions, approve/reject)
│   ├── automation.py      # Automation job visibility + Run Now
│   └── operations.py      # Data Intake partner state + activity feed
├── scheduler/      # APScheduler daemon (SFTP fetch, cron jobs)
│   └── jobs.py          # daily_partner_fetch_job, run_fetch_config_once
├── fetchers/       # SFTP, filedrop, API fetchers (base protocol + implementations)
├── logging/        # StructuredLogger (JSON/text formatters)
└── models/         # MongoDB models, repositories, indexes
    ├── repository.py         # Generic BaseRepository
    ├── indexes.py            # Index definitions + apply_indexes()
    ├── reconciliation_file.py  # File tracking model
    ├── mapping_config.py       # MappingConfig + MappingConfigStatus enum
    ├── data_container.py       # Canonical transaction model
    ├── internal_transaction.py # Internal records for reconciliation
    ├── reconciliation_result.py# Reconciliation output model
    ├── review_packet.py        # ReviewPacket + ReviewPacketRepository
    ├── copilot_action.py       # CopilotAction (audit trail for AI proposals)
    └── fetch_config.py         # FetchConfig for scheduler automation routes
frontend/           # Operations Dashboard (vanilla JS SPA + proxy)
├── index.html      # App shell
├── app.js          # Routing, rendering, filters (4800+ lines)
├── styles.css      # Responsive admin UI styles
├── vite.config.js  # Vite dev server config with /api proxy to FastAPI
├── server.py       # Legacy static file server (for reference)
└── README.md       # Frontend documentation
backend/            # Backend entry surface
├── app.py          # FastAPI app import surface for uvicorn
└── README.md       # Backend run notes
tests/              # 600+ unit/integration tests
├── test_api_review_packets.py   # Review packet approval endpoints
├── test_api_automation.py       # Automation job listing
├── test_api_automation_run.py   # Run Now real execution
├── test_api_mappings.py         # Mappings API v1
├── test_api_mapping_v2.py       # Mappings API v2 (ai-generate, validate, etc.)
├── test_api_insights.py         # AI insights endpoints
├── test_api_data_explorer.py    # Data explorer API
├── test_api_reconciliation.py   # Reconciliation results API
├── test_*.py                    # Core, config, readers, normalizer, pipeline, etc.
```

## MongoDB Collections

| Collection | Purpose | Key Indexes |
|------------|---------|-------------|
| `reconciliation_file` | Track uploaded files, processing stats | `fileHash` (unique), `partner + reconciliationDate` |
| `reconciliation_mapping_config` | Dynamic parsing configuration per partner | `partner + workflowType + fileType` |
| `data_container` | Canonical normalized transactions | `partnerData.trace`, `identify + reconciliationDate`, `operationStatus` |
| `internal_transaction` | Internal system records (Source of Truth) for reconciliation matching | `partnerTxnId`, `partner + transactionTime` |
| `reconciliation_result` | Reconciliation matching output with discrepancy reports | `partnerTxnId`, `reconciliationStatus`, `partner + date` (for AI queries) |
| `review_packet` | Central approval desk — every config proposal creates a packet. Status lifecycle: PENDING → APPROVED/REJECTED → SUPERSEDED | `status`, `partner`, `proposalConfigId` |
| `copilot_action` | Audit trail for AI-generated proposals (proposed mappings, confidence, reasoning) | `status`, `partner`, `targetConfigId` |
| `fetch_config` | Scheduler/automation route configuration per partner (fetch method, schedule, credentials) | `partner` |
| `apscheduler_jobs` | Persistent job scheduler state | `_id` |

## Configuration

All settings use `APP_` prefix environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `APP_DB_NAME` | `reconciliation` | Database name |
| `APP_LOG_LEVEL` | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `APP_LOG_FORMAT` | `json` | Log format (json/text) |
| `APP_APP_NAME` | `reconciliation-ingestion` | Application name |
| `ENCRYPTION_KEY` | None | Encryption/decryption key for sensitive partner credentials |

### AI Analysis Layer Configuration

All settings use `AI_` prefix environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `openai` | LLM provider type: `openai` \| `ollama` |
| `AI_MODEL` | `gpt-4o-mini` | Model name for the selected provider |
| `AI_ENDPOINT` | `https://api.openai.com/v1` | API endpoint URL (OpenAI-compatible) |
| `AI_API_KEY` | — | API key for the LLM provider |
| `AI_TIMEOUT` | `30` | HTTP timeout in seconds for LLM calls |
| `AI_MAX_RETRIES` | `2` | Maximum retry attempts on failure |
| `AI_ALERT_MISMATCH_RATE_THRESHOLD` | `5.0` | Mismatch rate % threshold for alerts |
| `AI_ALERT_MISSING_COUNT_THRESHOLD` | `10` | Missing transaction count threshold for alerts |

## Onboarding a New Partner

1. Insert a `MappingConfig` document into `reconciliation_mapping_config` with field mappings
2. No code changes needed — the platform reads config dynamically

Example MappingConfig:
```json
{
  "partner": "MOMO",
  "workflowType": "UPC",
  "fileType": "SETTLEMENT",
  "sheetName": "Sheet1",
  "startRow": 2,
  "fieldMappings": [
    { "path": "id", "column": "A", "type": "STRING", "required": true },
    { "path": "amount", "column": "D", "type": "DECIMAL" },
    { "path": "currency", "constant": "VND", "type": "CONSTANT" },
    { "path": "status", "column": "Q", "type": "MAPPING", "mapping": { "Thành công": "SUCCESS", "others": "FAILED" } }
  ]
}
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Decimal, never float | Prevent floating-point precision errors in financial calculations |
| partnerData as nested object | Easier MongoDB querying, indexing, aggregation |
| camelCase aliases in MongoDB | Matches requirement.md schema, industry standard |
| Error collection (not fail-fast) | Full audit trail — every row error is recorded |
| openpyxl read-only mode | Constant memory for large files (100K+ rows) |
| Reconciliation: deterministic by partnerTxnId | Same input always produces same classification output |
| Reconciliation: delete+re-insert pattern | Idempotent — safe to re-run without accumulating duplicates |
| Status normalization for Vietnamese | Matches Thành công / Thất bại / Hoàn tiền to standard TransactionStatus |
| AI: no raw data to LLM | Privacy-by-design — only aggregated metrics, grouped stats, pre-processed anomalies |
| AI: LLM fallback to rule-based | Graceful degradation — insights still available when LLM is unavailable |
| AI: provider abstraction | Swappable LLM backends (OpenAI-compatible, Ollama deferred) |
| Reconciliation: pre-check guard | Skip unnormalized records with warning log + `UNMAPPED_SKIPPED` status before processing — prevents silent errors and tracks in stats |
| Config health: structure signature fingerprint | MD5 of headers + column count provides cheap staleness detection before AI generation |
| Config health: error rate threshold (20%) | Failed-row ratio detects semantic drift (wrong columns, status values, date formats) even when header structure matches |
| Config health: PENDING_REVIEW for low confidence | AI-generated configs below 85% confidence require human approval before auto-application — prevents silent misconfiguration |
| Config health: self-healing pipeline | `check_and_refresh_config` runs before each ingestion; `record_config_run_health` runs after — ensures automatic recovery without manual intervention |
| Config health: PENDING_APPROVAL with review_packet | AI-generated proposals go through `ReviewPacket` before activation — no silent config switch |
| Approval model: review_packet as single source of truth | Every config-change attempt creates a packet (upload, scheduler, health drift). Operators approve/reject in one place |
| Approval: two distinct approve actions | "Approve & Activate Next Runtime" supersedes current config; "Approve Keep Current" uses config for this file only without replacing runtime |
| Mapping Studio: proposal handoff | "Open In Mapping Studio" passes full packet context (proposal config ID, sample rows, headers) — operator refines then returns to approve |
| Mapping Studio: 3-step guided flow | Upload → Preview/Tweak → Validate/Handoff reduces partner onboarding friction |
| Mapping Studio: version history on publish | Every publish snapshots the full config to a history collection — enables rollback and audit trail |
| Automation Run Now: real execution | Triggers actual `run_fetch_config_once()` — not a mock toast. Results appear immediately in packets and job status |
| Data Intake: computed partner state | `_compute_partner_state()` derives ACTIVE/BLOCKED/NEEDS_REVIEW/NO_ACTIVITY from configs, packets, and files — no hardcoded logic |
| Excel reader: fallback_on_missing_sheet | Graceful degradation when partner renames a sheet — logs warning instead of crashing the pipeline |
| UI: vanilla JS SPA | No build step, no framework dependency — serve `index.html` directly or via proxy server |

## License

Private — internal use only.
