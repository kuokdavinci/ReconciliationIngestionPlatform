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

### 3. Run Pipeline Ingestion CLI
You can execute the pipeline using `run.py`. When run, it connects to MongoDB, **automatically applies index recommendations**, downloads the file, and runs the ingestion:
```bash
# Run with a dynamic Excel configuration template (e.g. RequestTemplate.xlsx)
uv run python run.py --config /path/to/RequestTemplate.xlsx

# Run with existing config seed in MongoDB (uses default MOMO config)
uv run python run.py
```

### 4. Running Tests
To run unit and integration tests:
```bash
uv run python -m pytest -v
```

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
     ┌──────────────┐
     │  MongoDB     │  reconciliation_file, mapping_config, data_container
     └──────────────┘
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

## Key Features

- **Zero hardcoded parsers** — all column mapping, transformations, and status normalization are defined in MongoDB `MappingConfig` documents
- **Memory-efficient** — openpyxl read-only mode streams rows, constant memory regardless of file size
- **Duplicate prevention** — SHA256 file hash + composite key (identify + reconciliationDate + trace)
- **Batch insertion** — configurable batch size (default 100) for efficient MongoDB writes
- **Structured logging** — JSON output with 5 event types (FILE_STARTED, FILE_COMPLETED, FILE_FAILED, ROW_SUCCESS, ROW_FAILED)
- **Audit trail** — every record includes createdBy, createdDate, lastModifiedBy, lastModifiedDate

## Project Structure

```
src/
├── core/           # Canonical types, enums, constants
├── config/         # Settings, ConfigCache, ConfigValidator, ConfigLoader
├── readers/        # ExcelStreamReader (openpyxl read-only)
├── normalizer/     # TransactionNormalizer (dynamic field mapping)
├── validators/     # Validator (business rules + duplicate detection)
├── pipeline/       # IngestionPipeline (full orchestration)
├── logging/        # StructuredLogger (JSON/text formatters)
└── models/         # MongoDB models, repositories, indexes
tests/              # 318 tests across all modules
```

## MongoDB Collections

| Collection | Purpose | Key Indexes |
|------------|---------|-------------|
| `reconciliation_file` | Track uploaded files, processing stats | `fileHash` (unique), `partner + reconciliationDate` |
| `reconciliation_mapping_config` | Dynamic parsing configuration per partner | `partner + workflowType + fileType` |
| `data_container` | Canonical normalized transactions | `partnerData.trace`, `identify + reconciliationDate`, `operationStatus` |

## Configuration

All settings use `APP_` prefix environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `APP_DB_NAME` | `reconciliation` | Database name |
| `APP_LOG_LEVEL` | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `APP_LOG_FORMAT` | `json` | Log format (json/text) |
| `APP_APP_NAME` | `reconciliation-ingestion` | Application name |

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

## License

Private — internal use only.
