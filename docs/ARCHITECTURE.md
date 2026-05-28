# Architecture

## System Overview

The Reconciliation Ingestion Platform is a data pipeline that transforms heterogeneous partner settlement reports into a unified canonical transaction model. The core design principle is **dynamic configuration** — no hardcoded parsing logic, all mapping rules stored in MongoDB.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        IngestionPipeline                            │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────────┐  │
│  │ ExcelStream  │───▶│ Transaction  │───▶│      Validator        │  │
│  │   Reader     │    │  Normalizer  │    │  (duplicate detect)   │  │
│  └──────────────┘    └──────────────┘    └───────────┬───────────┘  │
│         ▲                    ▲                       │              │
│         │                    │                       ▼              │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────────┐  │
│  │ ConfigLoader │    │ MappingConfig│    │  DataContainerRepo    │  │
│  │  (cached)    │    │  (from DB)   │    │  (batch insert)       │  │
│  └──────────────┘    └──────────────┘    └───────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    StructuredLogger                         │    │
│  │  FILE_STARTED → ROW_SUCCESS/ROW_FAILED → FILE_COMPLETED     │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

### 1. `src/core/` — Canonical Contracts

Defines the shared type system that all modules depend on. No external dependencies beyond pydantic.

**Key types:**
- `CanonicalTransaction` — normalized output model (id, trace, amount:Decimal, currency, status, transDate, extra)
- `FieldMapping` — configuration for mapping source columns to canonical fields (`column: int` 1-based)
- `PartnerData` — original partner transaction as nested object
- `ValidationError` — structured error with field, reason, row, trace
- `ProcessingStats` — total/success/failed row counts

**Design principles:**
- All monetary amounts use `Decimal` — floats are rejected at the pydantic level
- Status values are `StrEnum` for JSON serialization compatibility
- Models use `populate_by_name=True` with camelCase aliases for MongoDB
- `column` field uses 1-based column numbers (not Excel letters) to match template format directly

### 2. `src/config/` — Configuration Engine

Three-layer architecture:

```
ConfigCache (TTL, thread-safe)
      ▲
      │
ConfigValidator (structural + coverage checks)
      ▲
      │
ConfigLoader (orchestrates cache → DB → validate → return)
```

**ConfigCache:**
- Key format: `{partner}:{workflow_type}:{file_type}:{version_or_latest}`
- TTL: 300 seconds default, lazy cleanup on `get()`
- Thread-safe via `threading.Lock`

**ConfigValidator:**
- Empty field_mappings check
- Duplicate path detection
- CONSTANT type requires non-empty value
- MAPPING type requires non-empty dict
- Required fields must have column or constant
- Column format validation skipped when column is int (1-based number); only validates string columns (must be uppercase letters A-Z, AA-ZZ)

**ConfigLoader:**
- `load_by_partner_type()` — latest config for partner/workflow/file_type
- `load_by_version()` — specific version lookup
- Validates before caching and returning
- Raises `ConfigLoadError` with structured `validation_errors`

### 3. `src/readers/` — File Input

`ExcelStreamReader` uses openpyxl in `read_only=True` mode for constant memory usage.

**Features:**
- Sheet selection by name or index
- Configurable `start_row` (1-based)
- Empty row skipping (all cells None or "")
- Summary/footer row pattern matching (7 patterns including Vietnamese: tổng, 合计, 总计, 小计)
- Context manager protocol for automatic workbook cleanup
- Factory method `from_mapping_config()` creates reader from MappingConfig

**Memory behavior:**
- openpyxl read-only mode uses ~10MB regardless of file size
- Rows are yielded as tuples via generator — no in-memory list
- Large files (100K+ rows) process without OOM

### 4. `src/normalizer/` — Data Transformation

`TransactionNormalizer` applies `FieldMapping` rules to raw row tuples.

**Input:** Row tuples from `ExcelStreamReader` (0-indexed). Column numbers in `FieldMapping.column` are 1-based and converted to 0-based index internally.

**Conversion types:**

| Type | Behavior |
|------|----------|
| STRING | Convert to str, reject None/empty |
| DECIMAL | Convert to Decimal, reject float |
| DATE | Parse against 4 whitelisted formats |
| CONSTANT | Use configured constant value |
| MAPPING | Dict lookup with "others" fallback |

**Error handling:**
- Never raises exceptions — all errors collected as `ValidationError`
- Source resolution by column number (precedence) or sourceField name
- `_resolve_source()` handles both int column numbers and string column letters, with fallback conversion between formats
- `build_canonical()` constructs `CanonicalTransaction` from normalized dict
- Extra fields not in canonical schema collected into `extra` dict
- Dot-separated paths like `"extra.service"` are nested: `extra["service"] = value`

### 5. `src/validators/` — Validation Layer

Two-tier validation:

**Sync `validate()`:**
- Required fields: id (non-empty), currency (non-empty)
- Decimal: amount must be non-negative
- Date: transDate must be datetime if present
- Status: must be valid `TransactionStatus` enum

**Async `validate_with_duplicates()`:**
- Runs core validation first
- Transaction duplicate: `identify + reconciliationDate + trace`
- File duplicate: `fileHash` lookup
- Repository injection is optional — graceful degradation when not provided

### 6. `src/models/` — Persistence Layer

**BaseRepository:** Generic async CRUD with pydantic model conversion.

**Three domain models:**

| Model | Collection | Purpose |
|-------|------------|---------|
| `ReconciliationFile` | `reconciliation_file` | Track file processing lifecycle |
| `MappingConfig` | `reconciliation_mapping_config` | Dynamic parsing configuration |
| `DataContainer` | `data_container` | Canonical normalized transactions |

**Key design:**
- All models use `populate_by_name=True` with camelCase aliases
- UUIDs stored as strings in MongoDB via `_to_mongo()` converter
- Decimals converted to `Decimal128` for MongoDB storage
- `partnerData` is nested `PartnerData` object (not JSON string)
- `DataContainerRepository.insert_many()` for batch insertion
- `_convert_special_types()` recursively handles nested UUIDs and Decimals

**Indexes (7 total):**
- `reconciliation_file`: `fileHash` (unique), `partner + reconciliation_date`
- `reconciliation_mapping_config`: `partner + workflow_type + file_type`
- `data_container`: `partnerData.trace`, `identify + reconciliation_date`, `operation_status`, `partnerData.status`, `source_file_id`

### 7. `src/pipeline/` — Orchestration

`IngestionPipeline.process_file()` is the single entry point:

```
1. Compute SHA256 file hash (async, thread pool for sync I/O)
2. Check file duplicate → return early if found
3. Create ReconciliationFile (PROCESSING status)
4. Load MappingConfig (cached or from DB)
5. Create ExcelStreamReader (from_mapping_config)
6. For each row:
   a. Normalize via TransactionNormalizer (passes row tuple directly — uses column numbers)
   b. Build CanonicalTransaction
   c. Validate (core validation only — file duplicate already checked at step 2)
   d. If valid → batch buffer; if invalid → collect error
   e. Flush batch when size reached
7. Flush remaining batch
8. Update ReconciliationFile stats + status (COMPLETED)
9. Emit log events
10. Return IngestionResult
```

**Error handling:**
- Per-row errors never stop the pipeline
- Exception at any level → status FAILED, partial stats returned
- Best-effort status update on failure

### 8. `src/logging/` — Structured Logging

`StructuredLogger` wraps Python's `logging` module with JSON formatter.

**Event types:**

| Event | Fields |
|-------|--------|
| FILE_STARTED | file_id, file_name, partner |
| FILE_COMPLETED | file_id, total, success, failed, duration_ms |
| FILE_FAILED | file_id, error |
| ROW_SUCCESS | file_id, row_number, trace, status |
| ROW_FAILED | file_id, row_number, trace, status, reason |

**Configuration:**
- Format: JSON or text (from `settings.log_format`)
- Level: configurable (from `settings.log_level`)
- Field sanitization: max 256 chars per value
- Thread-safe singleton via double-checked locking

## Data Flow

See [DATA_FLOW.md](DATA_FLOW.md) for detailed end-to-end flow.

## Threat Model

| Threat | Mitigation |
|--------|------------|
| Float precision in monetary values | Decimal enforced at pydantic level |
| Duplicate file ingestion | SHA256 hash unique index |
| Duplicate transaction ingestion | Composite key (identify + reconciliationDate + trace) |
| Memory exhaustion from large files | openpyxl read-only mode, streaming |
| Config injection via MappingConfig | ConfigValidator structural checks |
| Log field overflow | Sanitize to 256 chars max |
| Unindexed queries | 7 indexes defined, applied on startup |
