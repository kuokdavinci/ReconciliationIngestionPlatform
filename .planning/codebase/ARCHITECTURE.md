# Architecture

**Analysis Date:** 2026-06-23

## Pattern Overview

**Overall:** Modular monolith with clear layered separation — backend is a Python async service (`FastAPI`) with MongoDB persistence; frontend is a Next.js SPA consuming a REST API. The backend follows a Repository pattern over MongoDB, a Pipeline pattern for file ingestion, and a service-oriented module layout.

**Key Characteristics:**
- **Backend/frontend separated** — Python backend at `src/`, Next.js frontend at `frontend-next/`, no SSR coupling
- **Repository pattern** — Every MongoDB collection has a paired Repository class extending `BaseRepository[T]` at `src/models/repository.py`, isolating data access from business logic
- **Pipeline orchestration** — `IngestionPipeline` (`src/pipeline/ingestion_pipeline.py`) is the single orchestrator for file processing; `ReconciliationEngine` (`src/reconciliation/engine.py`) orchestrates transaction matching
- **AI Analysis Layer** — Separate analysis module at `src/analysis/` with provider abstraction, LLM fallback chain, guardrails, caching, and structured output schemas
- **Config-driven parsing** — `MappingConfig` (`src/models/mapping_config.py`) defines dynamic field mappings stored in MongoDB, loaded via `ConfigLoader` (`src/config/loader.py`) with TTL caching
- **Deterministic reconciliation** — `ReconciliationEngine` is stateless, batch-oriented, and purely deterministic — no ML or heuristics in matching logic
- **Actor-based operation** — Multi-tenant user context transmitted via `X-Actor` header (`frontend-next/src/lib/actor.ts`, `src/api/actor.py`), recorded on audit events

## Layers

**Core Layer:**
- Purpose: Shared enums, types, constants used by all other layers
- Location: `src/core/`
- Contains: `types.py` (CanonicalTransaction, FieldMapping, ProcessingStats), `enums.py` (ProcessingStatus, TransactionStatus, ReconciliationStatus, FileType), `constants.py`, `error_formatting.py`
- Depends on: Nothing internal
- Used by: All other layers

**Models & Repository Layer:**
- Purpose: Pydantic model definitions + MongoDB data access per collection
- Location: `src/models/`
- Contains: 15+ model/repository pairs — `DataContainer`, `MappingConfig`, `ReconciliationResult`, `InternalTransaction`, `ReconciliationFile`, `ReviewPacket`, `CopilotAction`, `AuditEvent`, `PartnerRuntimeRun`, `FetchConfig`, etc.
- Key base class: `BaseRepository[T]` at `src/models/repository.py` — provides `create`, `find_one`, `find_many`, `update_one`, `delete_one`, `insert_many`, plus MongoDB type conversion (Decimal↔Decimal128, UUID↔str)
- Depends on: `src/core/`, motor `AsyncIOMotorDatabase`
- Used by: Pipeline, Reconciliation Engine, API routers, Services

**Config Layer:**
- Purpose: Mapping configuration loading, caching, validation, health checking, and AI generation
- Location: `src/config/`
- Contains: `settings.py` (env-based `APP_` prefix), `loader.py` (`ConfigLoader`), `cache.py` (`ConfigCache` in-memory TTL), `validator.py` (`ConfigValidator`), `signature.py` (structure fingerprinting), `config_health.py` (stale detection + auto-generation), `ai_generator.py`
- Depends on: `src/models/mapping_config.py`, `src/core/`
- Used by: Pipeline, API routers (mappings)

**Pipeline Layer:**
- Purpose: End-to-end file ingestion: read → normalize → validate → persist
- Location: `src/pipeline/`
- Contains: `ingestion_pipeline.py` — `IngestionPipeline` single orchestrator with `process_file()`
- Depends on: Readers, Normalizer, Validator, Models/Repositories, Config Loader, Reconciliation Scope
- Used by: `run.py` (CLI), potentially API endpoints

**Reader Layer:**
- Purpose: Streaming file readers for CSV, Excel, JSON with row-by-row iteration
- Location: `src/readers/`
- Contains: `csv_reader.py` (`CSVStreamReader`), `excel_reader.py` (`ExcelStreamReader`), `json_reader.py` (`JSONStreamReader`), `__init__.py` (`create_reader` factory)
- Depends on: `src/models/mapping_config.py`
- Used by: Pipeline

**Normalizer Layer:**
- Purpose: Transform raw row data into canonical field values using FieldMapping rules
- Location: `src/normalizer/`
- Contains: `normalizer.py` — `TransactionNormalizer` with type conversion (STRING, DECIMAL, DATE, CONSTANT, MAPPING) and `build_canonical()` static method
- Depends on: `src/core/types.py`
- Used by: Pipeline

**Validator Layer:**
- Purpose: Business rule validation on canonical transactions
- Location: `src/validators/`
- Contains: `validator.py` — `Validator` with field checks, status validation, date integrity, duplicate detection
- Depends on: `src/core/`, `src/models/` (for duplicate lookups)
- Used by: Pipeline

**Reconciliation Layer:**
- Purpose: Compare partner transactions (DataContainer) vs internal transactions (InternalTransaction), produce ReconciliationResults
- Location: `src/reconciliation/`
- Contains: `engine.py` (`ReconciliationEngine` — async batch matching), `scope.py` (file scope classification — FULL_SNAPSHOT, INCREMENTAL_APPEND, REPLACEMENT, UNCONFIRMED)
- Depends on: Models (DataContainer, InternalTransaction, ReconciliationResult repositories)
- Used by: API routers, `run.py` (CLI)

**Scheduler Layer:**
- Purpose: Scheduled partner data fetching with persistent job store
- Location: `src/scheduler/`
- Contains: `scheduler.py` (`PartnerDataScheduler` wrapping APScheduler AsyncIOScheduler + MongoDBJobStore), `config.py` (`SchedulerConfig`), `jobs.py` (job definitions)
- Depends on: APScheduler, motor, Fetchers
- Used by: `run.py` (CLI)

**Fetcher Layer:**
- Purpose: Partner data retrieval from various sources
- Location: `src/fetchers/`
- Contains: `base.py` (`BaseFetcher` ABC with credential resolution, date interpolation, file validation), `sftp_fetcher.py`, `api_fetcher.py`, `filedrop_fetcher.py`
- Depends on: Models (FetchConfig), paramiko, aiohttp
- Used by: Scheduler jobs

**Analysis Layer:**
- Purpose: AI-powered insights, discrepancy analysis, daily reporting with LLM
- Location: `src/analysis/`
- Contains: `insights.py` (orchestration — `get_summary`, `get_discrepancies`, `generate_insights`), `metrics.py` (MetricsService), `grouping.py` (GroupingEngine), `provider.py` (AIProviderRouter with fallback chain), `providers/openai_compat.py`, `prompts.py`, `schemas.py`, `guardrails.py`, `cache.py`, `alerter.py`, `reporter.py`, `services.py`, `config.py`
- Depends on: `src/core/`, motor collection, LLM provider (OpenAI-compatible)
- Used by: API routers (insights)

**Services Layer:**
- Purpose: Thin helper services for cross-cutting operations
- Location: `src/services/`
- Contains: `audit.py` (audit event recording), `runtime_runs.py` (runtime run lifecycle), `runtime_validation.py`, `mapping_contract.py`, `review_packet_actions.py`, `ai_mapping_context.py`, `copilot_context.py`
- Depends on: `src/models/`
- Used by: API routers

**API Layer:**
- Purpose: FastAPI route handlers exposing endpoints for all domains
- Location: `src/api/`
- Contains: `__init__.py` (factory `create_app()` with lifespan MongoDB management), 11 routers: `insights.py`, `reconciliation.py`, `data_explorer.py`, `mappings.py`, `copilot.py`, `operations.py`, `review_packets.py`, `automation.py`, `audit.py`, `actor.py`, `response_utils.py`
- Depends on: All service layers, models, analysis, reconciliation engine
- Used by: `run.py --serve` (uvicorn)

**Logging Layer:**
- Purpose: Structured JSON logging with event types for file/row lifecycle
- Location: `src/logging/`
- Contains: `logger.py` — `StructuredLogger` with typed emit methods (`emit_file_started`, `emit_file_completed`, `emit_file_failed`, `emit_row_success`, `emit_row_failed`), JSON/Text formatters, singleton via `get_structured_logger()`
- Depends on: `src/config/settings.py`
- Used by: Pipeline, Reconciliation Engine

## Data Flow

**Ingestion Flow (file in → canonical transactions in MongoDB):**

1. **Read** → `run.py` reads Excel template or loads config, invokes `IngestionPipeline.process_file()`
2. **Dedup check** → Pipeline computes SHA256 hash, checks `ReconciliationFileRepository.find_by_file_hash()`
3. **Config load** → `ConfigLoader.load_by_partner_type()` or `load_by_version()` fetches + caches + validates `MappingConfig`
4. **Stream read** → `create_reader(file_path, config)` returns `ExcelStreamReader` / `CSVStreamReader` / `JSONStreamReader`; rows yielded one at a time via `iter_rows()`
5. **Normalize** → `TransactionNormalizer.normalize(row_tuple)` applies FieldMapping rules: column lookups → type conversions → produces `NormalizationResult.data` dict
6. **Build canonical** → `TransactionNormalizer.build_canonical(data)` constructs `CanonicalTransaction` with required field validation
7. **Validate** → `Validator.validate(txn)` checks fields, decimal, date, status; no fail-fast — collects all errors
8. **Persist** → Valid `DataContainer` objects batch-buffered (batch_size=100), flushed to `data_container` collection via `DataContainerRepository.insert_many()`
9. **Complete** → `ReconciliationFile` status updated to COMPLETED with stats; structured events emitted throughout

**Reconciliation Flow (canonical transactions → matching results):**

1. **Scope** → `classify_scope()` in `src/reconciliation/scope.py` infers scope from filename tokens
2. **Query partner** → MongoDB query on `data_container` for partner + date range
3. **Query internal** → MongoDB query on `internal_transaction` for partner + date range, filtered to finalized statuses (SUCCESS/FAILED/REVERSED)
4. **Build index** → `_build_internal_index()` creates `{partnerTxnId: {amount, status, updated_at}}` dict, de-duplicating by latest `updated_at`
5. **Batch iterate** → Partner records fetched in batches of 5000, key resolved via `_resolve_partner_txn_id()` (trace → vspTransId → id)
6. **Compare** → For each partner key found in internal index: compare amount + status → produce `ReconciliationStatus` (MATCHED, AMOUNT_MISMATCH, STATUS_MISMATCH, MULTIPLE_MISMATCH, MISSING_INTERNAL, MISSING_PARTNER, UNMAPPED_SKIPPED)
7. **Write** → Results batch-written to `reconciliation_result` collection in batches of 5000, clearing previous results for the partner/date

**AI Analysis Flow (reconciliation results → LLM insights):**

1. **Query** → `_query_summary_metrics()` runs MongoDB aggregation for status counts + mismatch amounts
2. **Group** → `GroupingEngine.group()` clusters results by status/amount range/date
3. **Pre-process** → `rule_based_pre_process()` identifies anomalies from raw data
4. **Build input** → `build_analysis_input()` constructs structured `AnalysisInput` with metrics, groups, anomalies, error signals
5. **Cache check** → TTL cache lookup by partner+date+focus+model+hash
6. **LLM call** → `AIProviderRouter.generate()` with fallback chain: primary → fallback provider → rule-based
7. **Parse** → `parse_structured_insight()` validates structured JSON output against `AnalysisResult` schema
8. **Guardrails** → `validate_insights()` cross-references LLM claims against actual data (risk level, unsupported claims, warnings)
9. **Return** → Insights returned with full observability metadata (latency, tokens, cost, cache hit, resolution path)

**Frontend → Backend Flow:**

1. **REST call** → Next.js client component calls API function in `frontend-next/src/lib/api/` (e.g., `reconciliation.ts`)
2. **HTTP fetch** → `client.ts` uses `fetch()` with `BASE_URL=/api/v1`, `X-Actor` header, typed `get<T>()` / `post<T>()` helpers
3. **FastAPI handler** → Router in `src/api/` validates params, calls service layers, returns JSON with `camelize()` response utility
4. **State update** → Frontend custom hooks like `useReconciliationStore()` in `frontend-next/src/lib/state/reconciliation-store.ts` manage local state
5. **Render** → Components read from store, display data in tables, grids, panels, dialogs

**State Management:**
- Backend: Stateless — all state in MongoDB; per-request database connection via app state lifespan
- Frontend: Local React state via custom hooks (`useState`/`useCallback` in custom stores) — no Redux/Zustand; mock data files at `frontend-next/src/lib/state/mock-*.ts` for UI development
- Cross-session: MongoDB persistence for all entities; audit events append-only

## Key Abstractions

**BaseRepository[T] (`src/models/repository.py`):**
- Purpose: Generic MongoDB CRUD foundation for all model repositories
- Methods: `create`, `find_one`, `find_many`, `update_one`, `delete_one`, `insert_many`
- Type conversion: UUID↔str via `_to_mongo()`/`_from_mongo()`, Decimal↔Decimal128 via `_convert_special_types()`/`_convert_from_mongo_types()`
- All model repos extend this: `DataContainerRepository`, `MappingConfigRepository`, `ReconciliationResultRepository`, `InternalTransactionRepository`, `ReconciliationFileRepository`, `AuditEventRepository`, `CopilotActionRepository`, etc.

**IngestionPipeline (`src/pipeline/ingestion_pipeline.py`):**
- Purpose: Single orchestrator for file → canonical transaction flow
- Key method: `process_file()` — async, ~200 lines, handles full lifecycle with error recovery and structured logging
- Returns: `IngestionResult` dataclass with `file_record`, `stats`, `errors`

**TransactionNormalizer (`src/normalizer/normalizer.py`):**
- Purpose: Apply FieldMapping rules to raw row tuples, convert types, collect errors
- Key methods: `normalize()` (returns NormalizationResult), `normalize_with_trace()` (adds field-level traces), `build_canonical()` (static, constructs CanonicalTransaction)
- Design: Never raises exceptions — all errors collected as ValidationError objects

**ReconciliationEngine (`src/reconciliation/engine.py`):**
- Purpose: Deterministic batch matching of partner vs internal transactions
- Key method: `reconcile(partner, reconciliation_date)` — async, returns `list[ReconciliationResult]`
- Design: Stateless, batch-oriented (PARTNER_BATCH_SIZE=5000, RESULT_WRITE_BATCH_SIZE=5000), handles scoped replacement/incremental modes

**ConfigLoader (`src/config/loader.py`):**
- Purpose: Orchestrate config loading with caching and validation
- Key methods: `load_by_partner_type()`, `load_by_version()`
- Design: Cache-first with DB freshness check; integrates `ConfigCache` (in-memory TTL) + `ConfigValidator`

**AIProviderRouter (`src/analysis/provider.py`):**
- Purpose: Route LLM calls through primary → fallback → rule-based fallback chain
- Key methods: `generate(user_prompt, system_prompt)` → returns structured response
- Design: Tracks resolution path (`llm`, `llm_fallback`, `rule_based`) for observability

**Frontend Hooks + Stores (`frontend-next/src/lib/`):**
- Purpose: Client-side state management and API communication
- Pattern: Custom React hooks (not Redux/Zustand) — `useReconciliationStore()`, `useReviewPackets()`, `useGuidedReview()`, `usePostApprovalPolling()`
- API layer: `get<T>()` / `post<T>()` in `client.ts` with typed per-domain modules (`reconciliation.ts`, `review-center.ts`, `mapping-studio.ts`, `audit.ts`, `automation.ts`)
- Mock data: `mock-reconciliation-data.ts`, `mock-review-center-data.ts`, `mock-mapping-data.ts`, `mock-schedules-data.ts`, `mock-audit-data.ts`

## Entry Points

**CLI — `run.py`:**
- Location: `/home/kuokdavinci/AdapterService/run.py`
- Triggers: `python run.py [--serve] [--reconcile YYYY-MM-DD] [--config template.xlsx] [--data file] [--start-scheduler]`
- Responsibilities: CLI argument parsing, MongoDB connection, index application, dispatch to scheduler/reconciliation/serve/ingestion modes
- Key dependency: `asyncio.run(main())`

**FastAPI Server — `src/api/__init__.py:create_app()`:**
- Location: `/home/kuokdavinci/AdapterService/src/api/__init__.py`
- Triggers: `uvicorn src.api:create_app --factory` (via `run.py --serve`)
- Responsibilities: Create FastAPI app, register 11 routers, manage MongoDB lifespan (connect on startup, close on shutdown), apply indexes
- Routers registered:
  - `insights_router` at `/api/v1/insights/*`, `/api/v1/reports/*`
  - `reconciliation_router` at `/api/v1/reconciliation/*`
  - `data_explorer_router` at `/api/v1/data-explorer/*`
  - `mappings_router` at `/api/v1/mappings/*`
  - `mappings_v2_router` at `/api/v1/v2/mappings/*`
  - `copilot_router` at `/api/v1/copilot/*`
  - `operations_router` at `/api/v1/operations/*`
  - `review_packets_router` at `/api/v1/review-packets/*`
  - `automation_router` at `/api/v1/automation/*`
  - `audit_router` at `/api/v1/audit/*`

**Next.js Frontend — `frontend-next/src/app/layout.tsx`:**
- Location: `/home/kuokdavinci/AdapterService/frontend-next/src/app/layout.tsx`
- Triggers: `npm run dev` or `npm run build && npm start`
- Responsibilities: Root layout with `AppShell` (sidebar grid) and `ToastProvider`
- Pages:
  - `/` → redirects to `/review-center`
  - `/review-center` → Guided review for runtime validation + mapping
  - `/reconciliation` → Reconciliation results viewer with evidence + insights
  - `/schedules` → Partner fetch schedule management
  - `/audit-log` → Audit event history

**Scheduler — `src/scheduler/scheduler.py:PartnerDataScheduler`:**
- Location: `/home/kuokdavinci/AdapterService/src/scheduler/scheduler.py`
- Triggers: `run.py --start-scheduler` or `--run-job-now`
- Responsibilities: APScheduler with MongoDB job store, daily partner fetch job

## Error Handling

**Strategy:** Never fail-fast — collect all errors. Normalization, validation, and pipeline processing collect errors as lists of `ValidationError` objects. The pipeline continues processing rows after errors. Reconciliation skips invalid records (UNMAPPED_SKIPPED).

**Patterns:**
- `ValidationError` pydantic model at `src/core/types.py` with `field`, `reason`, `row`, `trace`
- `NormalizationResult` dataclass with `data` + `errors` list
- `ValidationResult` dataclass with `is_valid` flag + `errors` list
- Pipeline: Per-row errors collected, batch processing continues, final stats reflect success/fail counts
- Reconciliation: `_pre_check_record()` skips invalid records with warning logs, produces UNMAPPED_SKIPPED results
- Analysis: LLM errors trigger fallback chain → rule-based results; guardrail rejection falls back to rule-based
- API: HTTPException with 400/503/500 status codes, detail messages

## Cross-Cutting Concerns

**Logging:** `StructuredLogger` at `src/logging/logger.py` — singleton with JSON/Text formatters, structured event types (FILE_STARTED, FILE_COMPLETED, FILE_FAILED, ROW_SUCCESS, ROW_FAILED), used by Pipeline and Reconciliation Engine

**Validation:** `Validator` at `src/validators/validator.py` — field presence, decimal non-negative, date type, status enum membership, duplicate detection (transaction-level + file-level via SHA256 hash)

**Authentication:** Actor-based via `X-Actor` HTTP header — `src/api/actor.py` reads/validates actor from header, `frontend-next/src/lib/actor.ts` stores/retrieves from `localStorage`. No OAuth/JWT — designed for internal tools

**Audit:** Append-only audit events at `src/models/audit_event.py` + `src/services/audit.py` — every reconciliation run, mapping change, review action is recorded

**Configuration:** `Settings` at `src/config/settings.py` using pydantic-settings with `APP_` env prefix, `.env` file support. Key configs: `APP_MONGODB_URL`, `APP_DB_NAME`, `APP_LOG_LEVEL`, `APP_LOG_FORMAT`, `APP_STRICT_MAPPING_APPROVAL_ENABLED`

---

*Architecture analysis: 2026-06-23*
