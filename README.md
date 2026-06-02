# Reconciliation Ingestion Platform

A configurable reconciliation ingestion platform that reads partner settlement reports, normalizes heterogeneous transaction data into a canonical model, and persists them into MongoDB — all driven by dynamic configuration with zero hardcoded parsing logic.

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
| `GET /stats?partner=X&date=Y` | Aggregated counts by status + total amounts |

**Data Explorer API** (`/api/v1/data`):

| Endpoint | Description |
|----------|-------------|
| `GET /transactions?partner=X&date=Y&trace=Z&status=W` | Browse DataContainer records with optional filters and pagination |
| `GET /transactions/{id}` | Get single transaction by UUID |
| `GET /files?partner=X&date=Y&status=Z` | List reconciliation files with optional filters |
| `GET /files/{id}` | Get file detail with associated transaction count |
| `GET /stats?partner=X&date=Y` | Aggregate data volume statistics |

### 7. Operations Dashboard (Web UI)

A browser-based dashboard for monitoring and managing the platform:

```bash
# Terminal 1 — Start the FastAPI backend
uv run python run.py serve --port 8000

# Terminal 2 — Start the dashboard proxy server
python web/server.py --port 5173 --api http://localhost:8000
```

Then open `http://localhost:5173` and switch `Data Source` to `Live API`.

**Dashboard Features:**
- **Overview** — Key metrics (files processed, success rates, anomaly counts) with a **Reconciliation Health** widget showing healthy/warning/anomaly status per partner
- **Scheduler** — View and manage automated ingestion jobs
- **Reconciliation** — Browse reconciliation results by partner and date
- **Mapping Configs** — View active mapping configurations per partner with field mapping details (column, type, required flag, mapping rules)
- **AI Insights** — LLM-generated insights, discrepancy analysis, daily reports
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
Partner Excel File
       ↓
┌─────────────────────────┐
│  ExcelStreamReader      │  openpyxl read-only, constant memory
│  (skip empty/summary)   │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  ConfigLoader           │  TTL cache, validation, version resolution
│  (MappingConfig)        │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  TransactionNormalizer  │  STRING/DECIMAL/DATE/MAPPING/CONSTANT
│  (dynamic mapping)      │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  Validator              │  Required fields, decimal, date, status
│  (duplicate detection)  │  identify + reconciliationDate + trace
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  IngestionPipeline      │  Orchestration, batch insert, logging
│  (process_file)         │  SHA256 dedup, stats tracking
└───────────┬─────────────┘
            ↓
     ┌──────────────┐          ┌─────────────────────────────────────┐
     │  MongoDB     │◀─────────│  ReconciliationEngine               │
     │              │          │  (key=partnerTxnId, match +         │
     │ data_container│          │   classify, generates results)      │
     │ internal_    │          └─────────────────────────────────────┘
     │  transaction │                       ↑
     │ reconciliation│          ┌────────────┴────────────┐
     │  _result     │          │  InternalTransactionRepo  │  (Mock DB)
     │ mapping_config│          └─────────────────────────┘
     │ reconciliation│
     │  _file       │
     └──────┬───────┘
            │
            ↓
┌───────────────────────────────────────────────────────────┐
│  AI Analysis Layer (src/analysis/)                        │
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ MetricsSvc  │  │ GroupingEng  │  │ LLMProvider     │  │
│  │ (stats)     │  │ (buckets)    │  │ (GPT-4o/Ollama) │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬────────┘  │
│         │                │                    │           │
│         └────────┬───────┘                    │           │
│                  ↓                            │           │
│  ┌────────────────────────────────────────┐   │           │
│  │  insights.py (orchestration)           │   │           │
│  │  query → metrics → grouping → LLM      │   │           │
│  └──────────────────┬─────────────────────┘   │           │
│                     │                         │           │
│  ┌──────────────────┴─────────────────────┐   │           │
│  │  FastAPI Server (src/api/)             │   │           │
│  │  GET /api/v1/insights/summary          │   │           │
│  │  GET /api/v1/insights/discrepancies    │   │           │
│  │  GET /api/v1/reports/daily             │   │           │
│  │  GET /api/v1/reconciliation/results    │   │           │
│  │  GET /api/v1/reconciliation/stats      │   │           │
│  │  GET /api/v1/data/transactions         │   │           │
│  │  GET /api/v1/data/files                │   │           │
│  │  GET /api/v1/data/stats                │   │           │
│  │  GET /api/v1/mappings                  │   │           │
│  └──────────────┬─────────────────────────┘               │
│                 │                                          │
│                 ▼                                          │
│  ┌─────────────────────────────┐                          │
│  │  Web Dashboard (web/)       │                          │
│  │  Overview · Scheduler       │                          │
│  │  Reconciliation · Mapping   │                          │
│  │  Configs · AI Insights      │                          │
│  └─────────────────────────────┘                          │
└───────────────────────────────────────────────────────────┘
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
- **FastAPI REST API** — serves AI insights, reconciliation results, data explorer, and mapping config endpoints
- **Operations Dashboard** — browser-based UI with Overview, Reconciliation, Mapping Configs, AI Insights tabs
- **Data flow guard** — ReconciliationEngine pre-checks each partner record for valid normalized data before processing; invalid records are skipped with structured warning logs and tracked in stats

## Project Structure

```
src/
├── core/           # Canonical types, enums, constants (incl. ReconciliationStatus)
├── config/         # Settings, ConfigCache, ConfigValidator, ConfigLoader
├── readers/        # ExcelStreamReader (openpyxl read-only)
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
│   └── mappings.py        # Mapping config API (GET /api/v1/mappings)
├── scheduler/      # APScheduler daemon (SFTP fetch, cron jobs)
├── logging/        # StructuredLogger (JSON/text formatters)
└── models/         # MongoDB models, repositories, indexes
web/                # Operations Dashboard (vanilla JS SPA)
├── index.html      # App shell
├── app.js          # Routing, rendering, filters
├── styles.css      # Responsive admin UI styles
├── server.py       # Static server with /api proxy to FastAPI
└── README.md       # Dashboard documentation
tests/              # 600+ unit/integration tests
```

## MongoDB Collections

| Collection | Purpose | Key Indexes |
|------------|---------|-------------|
| `reconciliation_file` | Track uploaded files, processing stats | `fileHash` (unique), `partner + reconciliationDate` |
| `reconciliation_mapping_config` | Dynamic parsing configuration per partner | `partner + workflowType + fileType` |
| `data_container` | Canonical normalized transactions | `partnerData.trace`, `identify + reconciliationDate`, `operationStatus` |
| `internal_transaction` | Internal system records (Source of Truth) for reconciliation matching | `partnerTxnId`, `partner + transactionTime` |
| `reconciliation_result` | Reconciliation matching output with discrepancy reports | `partnerTxnId`, `reconciliationStatus`, `partner + date` (for AI queries) |
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
| UI: vanilla JS SPA | No build step, no framework dependency — serve `index.html` directly or via proxy server |

## License

Private — internal use only.
