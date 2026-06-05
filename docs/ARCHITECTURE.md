# Architecture

## System Overview

The Reconciliation Ingestion Platform is a data pipeline that transforms heterogeneous partner settlement reports into a unified canonical transaction model. The core design principle is **dynamic configuration** — no hardcoded parsing logic, all mapping rules stored in MongoDB.

## High-Level Architecture

```
                         ┌──────────────────────────────────────────┐
                         │          Operations Dashboard            │
                         │    (frontend/ — Vanilla JS SPA)          │
                         │                                          │
                         │  Command Center · Data Intake            │
                         │  Review Queue · Reconciliation           │
                         │  Mapping Studio · Automation             │
                         └─────────────┬────────────────────────────┘
                                       │ HTTP /api/*
                                       ▼
┌────────────────────────────────────────────────────────────────────┐
│                     FastAPI Server (src/api/)                       │
│                                                                    │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐  │
│  │  operations.py │  │ review_packets │  │  automation.py       │  │
│  │  GET /intake   │  │ GET/POST ...   │  │  GET /jobs           │  │
│  └───────┬────────┘  │ approve/*      │  │  POST /{p}/run      │  │
│          │           │ reject          │  └──────────┬───────────┘  │
│          │           │ send-to-studio  │             │              │
│          │           └───────┬─────────┘             │              │
│  ┌───────┴────────┐  ┌───────┴─────────┐  ┌─────────┴───────────┐  │
│  │  mappings.py   │  │  insights.py    │  │  reconciliation.py  │  │
│  │  /mappings/*   │  │  /insights/*    │  │  /reconciliation/*  │  │
│  │  /mapping/*    │  │  /reports/*     │  │  /data/*            │  │
│  └───────┬────────┘  └───────┬─────────┘  └─────────────────────┘  │
│          │                    │                                      │
│          └────────┬───────────┘                                      │
│                   ▼                                                  │
│          ┌──────────────────────┐          ┌──────────────────────┐  │
│          │  AI Analysis Layer   │          │  Reconciliation      │  │
│          │  (insights.py)       │          │  Engine              │  │
│          └──────────┬───────────┘          └──────────┬───────────┘  │
└─────────────────────┼────────────────────────────────┼──────────────┘
                      │                                │
                      ▼                                ▼
     ┌──────────────────────────────────────────────────────────┐
     │                      MongoDB                              │
     │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │
     │  │ data_        │  │ internal_    │  │reconciliation_ │  │
     │  │ container    │  │ transaction  │  │  result        │  │
     │  ├──────────────┤  ├──────────────┤  ├────────────────┤  │
     │  │reconciliation│  │reconciliation│  │ review_packet  │  │
     │  │  _file       │  │_mapping_    │  │                │  │
     │  │              │  │ config (OR   │  │ PENDING →      │  │
     │  │              │  │ PENDING_     │  │ APPROVED /     │  │
     │  │              │  │ APPROVAL /   │  │ REJECTED       │  │
     │  │              │  │ APPROVED /   │  │                │  │
     │  │              │  │ SUPERSEDED)  │  │                │  │
     │  ├──────────────┤  ├──────────────┤  ├────────────────┤  │
     │  │ copilot_     │  │ fetch_config │  │ apscheduler_   │  │
     │  │ action       │  │              │  │ jobs           │  │
     │  └──────────────┘  └──────────────┘  └────────────────┘  │
     └──────────────────────────────────────────────────────────┘
                           ▲
              ┌────────────┴────────────────┐
              │    Config Health             │
              │  (src/config/config_health)  │
              │                              │
              │  1. compute_signature()       │
              │  2. Detect stale config        │
              │  3. AI generate proposal       │
              │  4. Create ReviewPacket        │
              └───────────────────────────────┘
                           ▲
              ┌────────────┴────────────────┐
              │  Scheduler (APScheduler)     │
              │  (src/scheduler/jobs.py)     │
              │                              │
              │  • daily_partner_fetch_job   │
              │  • run_fetch_config_once     │
              │  → creates ReviewPacket      │
              └──────────────────────────────┘
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

**Five domain models:**

| Model | Collection | Purpose |
|-------|------------|---------|
| `ReconciliationFile` | `reconciliation_file` | Track file processing lifecycle |
| `MappingConfig` | `reconciliation_mapping_config` | Dynamic parsing configuration |
| `DataContainer` | `data_container` | Canonical normalized transactions |
| `InternalTransaction` | `internal_transaction` | Internal system records (Source of Truth) for reconciliation |
| `ReconciliationResult` | `reconciliation_result` | Output of reconciliation matching & classification |

**Key design:**
- All models use `populate_by_name=True` with camelCase aliases
- UUIDs stored as strings in MongoDB via `_to_mongo()` converter
- Decimals converted to `Decimal128` for MongoDB storage
- `partnerData` is nested `PartnerData` object (not JSON string)
- `DataContainerRepository.insert_many()` for batch insertion
- `_convert_special_types()` recursively handles nested UUIDs and Decimals

**Indexes (11 total):**
- `reconciliation_file`: `fileHash` (unique), `partner + reconciliation_date`
- `reconciliation_mapping_config`: `partner + workflow_type + file_type`
- `data_container`: `partnerData.trace`, `identify + reconciliation_date`, `operation_status`, `partnerData.status`, `source_file_id`
- `internal_transaction`: `partnerTxnId`, `partner + transactionTime`
- `reconciliation_result`: `partnerTxnId`, `reconciliationStatus`

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

### 9. `src/reconciliation/` — Reconciliation Engine

`ReconciliationEngine` implements deterministic transaction matching between ingested partner data (DataContainer) and internal system records (InternalTransaction).

**Core logic (in `reconcile()`):**

```
1. Calculate day boundaries (start_of_day / end_of_day)
2. Fetch partner records: DataContainerRepository.find_many({identify, reconciliationDate})
3. Fetch internal records: InternalTransactionRepository.find_many({partner, transactionTime})
4. Resolve duplicates: latest updatedAt wins for same partnerTxnId
5. For each partner record:
   a. Resolve partnerTxnId from (trace → vspTransId → id)
   b. Look up matching internal record
   c. If found: compare amount + normalized status → classify
   d. If not found: MISSING_INTERNAL
6. For each unmatched internal record: MISSING_PARTNER
7. Idempotent write: delete existing results for matching keys, then insert new
```

**Status normalization (`_normalize_status()`):**
- Vietnamese status strings (Thành công, Thất bại, Hoàn tiền) mapped to standard `TransactionStatus`
- Case-insensitive matching with fallback to PENDING

**Duplicate resolution:**
- Multiple internal records for same `partnerTxnId` → keep the one with latest `updatedAt`

**Classification matrix:**

| Condition | Result |
|-----------|--------|
| Key matches, amount matches, status matches | `MATCHED` |
| Key matches, amount differs (status ignored) | `AMOUNT_MISMATCH` |
| Key matches, amount matches, status differs | `STATUS_MISMATCH` |
| Key matches, amount differs, status differs | `MULTIPLE_MISMATCH` |
| Partner record exists, no internal record | `MISSING_INTERNAL` |
| Internal record exists, no partner record | `MISSING_PARTNER` |

**Idempotency:** Before inserting new results, existing `reconciliation_result` documents with the same `_id` (partnerTxnId) are deleted, making repeated runs safe.

### 10. `src/analysis/` — AI Analysis Layer

`ReconciliationEngine` output (`reconciliation_result`) is consumed by the AI Analysis Layer to generate actionable insights for operators.

**Architecture:**
```
┌───────────────────────────────────────────────────────────────┐
│                   AI Analysis Layer                            │
│                                                               │
│  ┌──────────────────────────────────────────────┐             │
│  │         insights.py (orchestration)           │             │
│  │  query → metrics → grouping → LLM enrich     │             │
│  └────────────────────┬─────────────────────────┘             │
│                       │                                       │
│            ┌──────────┴──────────┐                            │
│            ▼                     ▼                             │
│  ┌─────────────────┐  ┌──────────────────────┐                │
│  │  services.py    │  │  LLMProvider         │                │
│  │  (helpers only) │  │  (Protocol)          │                │
│  │  • AnalysisInput│  │  generate(prompt)    │                │
│  │    builder      │  │       → str          │                │
│  │  • LLM response │  └──────────┬───────────┘                │
│  │    parser       │             │                            │
│  └─────────────────┘             ▼                            │
│                    ┌──────────────────────────┐               │
│                    │  OpenAICompatProvider    │               │
│                    │  (GPT-4o, default)       │               │
│                    └──────────────────────────┘               │
│                                                               │
│  ┌──────────────┐  ┌───────────────────┐  ┌──────────────┐   │
│  │ FastAPI:     │  │ DailyReporter     │  │ Alerter      │   │
│  │ /insights/   │  │ (scheduled)       │  │ (threshold)  │   │
│  │  summary     │  │ format only       │  │ check only   │   │
│  │ /insights/   │  │                   │  │              │   │
│  │  discrepan-  │  │                   │  │              │   │
│  │  cies        │  │                   │  │              │   │
│  │ /reports/    │  │                   │  │              │   │
│  │  daily       │  │                   │  │              │   │
│  └──────────────┘  └───────────────────┘  └──────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

**Key components:**

| Component | Role | Description |
|-----------|------|-------------|
| `LLMProvider` (Protocol) | Abstract contract | `generate(prompt, system_prompt?) → str` — swappable providers |
| `OpenAICompatProvider` | GPT-4o implementation | `httpx.AsyncClient` with retry, timeout, low temperature (0.1) |
| `AnalysisConfig` | Settings | `AI_` env prefix: provider, model, endpoint, timeout, retries, alert thresholds |
| `AnalysisInput` | Data contract | Privacy-by-design: no raw transaction data, only aggregated metrics |
| `GroupingEngine` | Pure function | Group by status, amount range (0-100k, 100k-1M, 1M+), partner |
| `MetricsService` | Single source of truth | mismatch_rate, total_volume, avg_mismatch_amount, count_by_status |
| `insights.py` | Orchestration | `get_summary()`, `get_discrepancies()`, `generate_insights()` |
| `services.py` | Helpers | `build_analysis_input()`, `parse_llm_insights()`, `format_findings()` |
| `DailyReporter` | Format only | Generates daily batch reports using `insights.get_summary()` |
| `ThresholdAlerter` | Check only | Detects threshold breaches from config, severity scaling |

**Design principles:**
- **No raw data to LLM** — only aggregated metrics, grouped stats, and pre-processed anomalies
- **MetricsService is single source of truth** — reporter and alerter never duplicate computation
- **LLM fallback** — if LLM fails, returns rule-based insights only
- **Provider abstraction** — OpenAI-compatible (GPT-4o) default, OllamaProvider deferred
- **Deterministic output** — same input → same output (low temperature, structured JSON)

### 11. `src/api/` — FastAPI Server

FastAPI application serving all platform API endpoints.

**Insights Endpoints:**

| Method | Path | Description | Parameters |
|--------|------|-------------|------------|
| `GET` | `/api/v1/insights/summary` | Insight summary with groups and key findings | `partner`, `date` |
| `GET` | `/api/v1/insights/discrepancies` | LLM-powered deep analysis by focus type | `partner`, `date`, `focus` |
| `GET` | `/api/v1/reports/daily` | Daily batch report | `date` |

**Reconciliation & Data Explorer Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/reconciliation/results` | Reconciliation results with optional status filter |
| `GET` | `/api/v1/reconciliation/stats` | Aggregated reconciliation stats |
| `GET` | `/api/v1/data/transactions` | Browse canonical transactions |
| `GET` | `/api/v1/data/files` | List reconciliation files |
| `GET` | `/api/v1/data/stats` | Data volume statistics |

**Mappings Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/mappings` | List mapping configs |
| `POST` | `/api/v1/mapping/ai-generate` | Upload sample → AI generates field mappings |
| `POST` | `/api/v1/mapping/validate` | Validate mapping config rules |
| `POST` | `/api/v1/mapping/test` | Test transformation against sample data |
| `POST` | `/api/v1/mapping/publish` | Publish config to MongoDB with version snapshot |
| `GET` | `/api/v1/mapping/versions` | List published config versions |
| `GET` | `/api/v1/mapping/version/{id}` | Get specific version |

**Operations Endpoints (Data Intake):**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/operations/intake` | Partner intake summary + detail with pending items |

**Review Packet Endpoints (Approval Desk):**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/review-packets` | List pending/historic review packets |
| `GET` | `/api/v1/review-packets/{packet_id}` | Get packet detail |
| `POST` | `/api/v1/review-packets/{packet_id}/approve-activate` | Approve + activate next runtime |
| `POST` | `/api/v1/review-packets/{packet_id}/approve-keep-current` | Approve but keep current runtime |
| `POST` | `/api/v1/review-packets/{packet_id}/reject` | Reject proposal |
| `POST` | `/api/v1/review-packets/{packet_id}/send-to-studio` | Handoff to Mapping Studio |

**Automation Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/automation/jobs` | List enabled fetch configs with pending packet counts |
| `POST` | `/api/v1/automation/jobs/{partner}/run` | Execute Run Now (real fetch + ingest + config health) |

**Startup:** `python run.py serve` (uvicorn on port 8000, configurable via `--port`)

**Lifespan:** MongoDB connection managed via FastAPI lifespan context manager.

### 12. `src/api/operations.py` — Data Intake & Partner State

Provides the operational overview for the Data Intake dashboard.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/operations/intake` | Partner-level intake summary with state, files, and pending items |

**Key logic:**
- `_compute_partner_state()` — derives ACTIVE / NEEDS_REVIEW / BLOCKED / NO_ACTIVITY per partner based on approved configs, pending proposals, pending review packets, and latest file
- `_build_activity_items()` — merges FILE/CONFIG/ACTION/REVIEW events into a unified, reverse-chronological activity feed
- Returns both a summary array (all partners) and a detailed view (selected partner)

### 13. `src/api/review_packets.py` — Approval Desk

Central approval endpoints for `ReviewPacket` lifecycle.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/review-packets` | List packets (optional `status`, `partner` filters) |
| `GET` | `/api/v1/review-packets/{packet_id}` | Get single packet |
| `POST` | `/api/v1/review-packets/{packet_id}/approve-activate` | Approve and supersede current runtime config |
| `POST` | `/api/v1/review-packets/{packet_id}/approve-keep-current` | Approve but keep current runtime config for this file |
| `POST` | `/api/v1/review-packets/{packet_id}/reject` | Reject proposal |
| `POST` | `/api/v1/review-packets/{packet_id}/send-to-studio` | Send packet context to Mapping Studio for refinement |

**Approve-activate flow:**
1. Find proposal config via `proposalConfigId`
2. Find current approved config → set status to `SUPERSEDED`
3. Set proposal config status to `APPROVED`
4. Mark packet as `APPROVED` with `decisionMode=APPROVE_ACTIVATE_NEXT_RUNTIME`
5. Sync `CopilotAction` status to `APPROVED`

### 14. `src/api/automation.py` — Automation Visibility

Provides visibility into scheduled fetch configs and their review packet output.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/automation/jobs` | List all enabled fetch configs with pending packet counts and recent packets |
| `POST` | `/api/v1/automation/jobs/{partner}/run` | Trigger real `run_fetch_config_once()` execution |

**Key features:**
- Aggregates `FetchConfig` with `ReviewPacket` data per partner
- `pendingReviewPackets` count shows how many SCHEDULER_JOB packets are waiting
- `recentPackets[0..2]` shows latest packet status per job
- Run Now executes actual fetch → ingest → config health pipeline (not a mock)

### 15. `src/config/config_health.py` — Self-Healing Config

Config health detection that creates approval-gated proposals when partner file formats change.

**Key functions:**

| Function | Description |
|----------|-------------|
| `check_and_refresh_config()` | Detects stale config via `compute_signature()`, triggers AI proposal + `ReviewPacket` creation |
| `record_config_run_health()` | Records error rate after ingestion, marks config stale if > 20% |
| `_create_mapping_proposal()` | Creates `MappingConfig` (PENDING_APPROVAL) + `CopilotAction` + `ReviewPacket` atomically |

**Flow:**
1. `check_and_refresh_config()` reads file signature via `compute_signature()`
2. Compares against saved signature in current approved `MappingConfig`
3. If stale or no config exists → calls `_create_mapping_proposal()`
4. AI generates field mappings via `generate_config_from_samples()`
5. Proposal saved as `PENDING_APPROVAL` → `ReviewPacket` created → pipeline pauses or continues based on config availability

### 16. `src/models/review_packet.py` — Review Packet Model

The central approval document for all config-change proposals.

**`ReviewPacketStatus`:** PENDING → APPROVED / REJECTED / SUPERSEDED

**`ReviewDecisionMode`:**
- `APPROVE_ACTIVATE_NEXT_RUNTIME` — approve + supersede current config
- `APPROVE_KEEP_CURRENT_FOR_FILE` — approve, keep current runtime
- `REJECT` — deny proposal
- `SEND_TO_MAPPING_STUDIO` — route to Mapping Studio for refinement

**`ReviewPacket` fields:**
- `sourceType` — UPLOAD or SCHEDULER_JOB
- `proposalConfigId` — reference to the `MappingConfig` proposal
- `activeRuntimeConfigId` — current approved config (if any)
- `recommendedAction` — AI's suggested action type + confidence
- `parseStrategy` — sheet name, start row, field mapping count
- `validationGates` — structured pass/warn/fail checks
- `samplePreview` — first 5 sample rows from the source file
- `riskSummary` — severity + summary text

### 17. `src/models/copilot_action.py` — Copilot Action Audit Trail

Audit log for every AI-generated proposal.

**`CopilotActionType`:** `MAPPING_PROPOSAL`

**`CopilotActionStatus`:** `PENDING_APPROVAL` → `APPROVED` / `REJECTED`

**Fields:** partner, workflow type, file type, target config ID, payload (proposed mappings, sheet, signature, confidence, reasoning), reason.

### 18. `src/models/fetch_config.py` — Automation Route Config

Defines scheduler/automation routes per partner.

**`FetchMethod`:** SFTP, FILEDROP, HTTP_POLL

**Fields:** partner, fetch method, schedule (cron expression), enabled, local download dir, remote path / URL, credentials (encrypted), next fetch window.

## Data Flow

See [DATA_FLOW.md](DATA_FLOW.md) for detailed end-to-end flow including AI Analysis Layer.

## Threat Model

| Threat | Mitigation |
|--------|------------|
| Float precision in monetary values | Decimal enforced at pydantic level |
| Duplicate file ingestion | SHA256 hash unique index |
| Duplicate transaction ingestion | Composite key (identify + reconciliationDate + trace) |
| Memory exhaustion from large files | openpyxl read-only mode, streaming |
| Config injection via MappingConfig | ConfigValidator structural checks |
| Log field overflow | Sanitize to 256 chars max |
| Unindexed queries | 13+ indexes defined across 8 collections, applied on startup |
| Reconciliation: duplicate internal records for same partnerTxnId | Latest updatedAt wins (deterministic tie-break) |
| Reconciliation: non-idempotent results | Delete-many + insert-many pattern for matching keys |
| Reconciliation: Vietnamese/non-standard status strings | Normalized via _normalize_status() before comparison |
| Unauthorized config activation without review | `MappingConfig.status == PENDING_APPROVAL` blocks ingestion; requires explicit `APPROVE_ACTIVATE_NEXT_RUNTIME` via API |
| Stale config silently processing wrong format | `check_and_refresh_config()` runs before each ingestion; structure signature fingerprint detects format shifts |
| Duplicate review packets for same partner | `_create_mapping_proposal()` reuses existing pending proposal + action; only creates new `ReviewPacket` if none exists |
| Automation auto-approval missing human review | Automation mode is "Recommend Only" — never auto-approves; always creates `ReviewPacket` in PENDING status |
| Packet source type spoofing | `sourceType` (UPLOAD/SCHEDULER_JOB) is set at creation and never mutated |
