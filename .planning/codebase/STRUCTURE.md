# Codebase Structure

**Analysis Date:** 2026-06-23

## Directory Layout

```
AdapterService/
├── run.py                          # CLI entry point (ingestion, reconciliation, scheduler, server)
├── pyproject.toml                  # Python project config (dependencies, tooling)
├── requirements.txt                # Legacy pip requirements
├── Dockerfile                      # Production Docker build
├── Dockerfile.api                  # API-server-specific Docker build
├── docker-compose.yml              # Local dev environment (MongoDB, SFTP, etc.)
├── Makefile                        # Dev commands (lint, test, run)
│
├── src/                            # Python backend
│   ├── core/                       # Shared enums, types, constants
│   ├── config/                     # Settings, config loading, caching, validation
│   ├── models/                     # Pydantic models + MongoDB repositories
│   ├── readers/                    # Streaming file parsers (CSV, Excel, JSON)
│   ├── normalizer/                 # Field mapping → canonical transaction
│   ├── validators/                 # Business rule validation
│   ├── pipeline/                   # Ingestion pipeline orchestrator
│   ├── reconciliation/             # Transaction matching engine + scope classification
│   ├── fetchers/                   # Partner data retrieval (SFTP, API, filedrop)
│   ├── scheduler/                  # APScheduler-based job scheduling
│   ├── analysis/                   # AI analysis layer (LLM, guardrails, grouping, metrics)
│   │   └── providers/              # LLM provider implementations (OpenAI-compatible)
│   ├── api/                        # FastAPI routers (11 endpoints)
│   ├── services/                   # Thin service helpers (audit, runtime runs, review packets)
│   └── logging/                    # Structured JSON logger
│
├── frontend-next/                  # Next.js frontend
│   └── src/
│       ├── app/                    # Next.js App Router pages
│       ├── components/             # React components (ui, layout, domain-specific)
│       ├── lib/                    # API client, state stores, actor management
│       │   ├── api/                # Typed API modules per domain
│       │   └── state/              # Custom React hooks + mock data
│       └── types/                  # TypeScript type definitions
│
├── tests/                          # Python test suite (pytest)
│   ├── conftest.py                 # Shared fixtures, MongoDB mock
│   └── test_*.py                   # Per-module test files
│
├── docs/                           # Documentation
├── scripts/                        # Utility scripts
├── docker/                         # Docker compose / Dockerfile support files
├── mock_data/                      # Test fixture files (Excel, CSV)
├── sftp_data/                      # SFTP fallback data directory
├── tmp_downloads/                  # Runtime temp download directory
├── scratch/                        # Temporary upload workspace
└── reports/                        # Generated report output
```

## Directory Purposes

**`src/core/`:**
- Purpose: Shared foundation types that everything depends on — no internal imports
- Contains: Enums (`ProcessingStatus`, `TransactionStatus`, `ReconciliationStatus`, `FileType`, `ReconciliationScopeType`), types (`CanonicalTransaction`, `FieldMapping`, `PartnerData`, `ValidationError`, `ProcessingStats`), constants (`DUPLICATE_KEY_PATTERN`, `DEFAULT_CURRENCY`), error formatting
- Key files: `types.py` (104 lines), `enums.py` (51 lines), `constants.py` (7 lines)

**`src/config/`:**
- Purpose: Application settings, mapping config management, health checks
- Contains: `settings.py` (pydantic-settings `APP_` prefix), `loader.py` (ConfigLoader orchestrator), `cache.py` (in-memory TTL cache), `validator.py` (field mapping integrity), `signature.py` (file structure fingerprinting), `config_health.py` (stale detection + auto-generation), `ai_generator.py`
- Key files: `settings.py` (27 lines), `loader.py` (259 lines)

**`src/models/`:**
- Purpose: All data models + MongoDB data access layer
- Contains: `repository.py` (BaseRepository generic), 15 model files — `data_container.py`, `mapping_config.py`, `reconciliation_result.py`, `reconciliation_file.py`, `reconciliation_run.py`, `internal_transaction.py`, `review_packet.py`, `audit_event.py`, `copilot_action.py`, `partner_runtime_run.py`, `post_approval_run.py`, `fetch_config.py`, `indexes.py`, `reconciliation_review_record.py`
- Key files: `repository.py` (122 lines), `data_container.py` (161 lines), `mapping_config.py` (167 lines), `reconciliation_result.py` (160 lines), `indexes.py` (184 lines)

**`src/readers/`:**
- Purpose: Streaming row-by-row file readers
- Contains: Factory `create_reader()` dispatching by extension; `CSVStreamReader`, `ExcelStreamReader`, `JSONStreamReader`
- Key files: `__init__.py` (29 lines), all implement `.iter_rows()` for row iteration

**`src/normalizer/`:**
- Purpose: Transform raw rows → canonical field values
- Key file: `normalizer.py` (520 lines) — contains `TransactionNormalizer` with type conversion methods and `build_canonical` static

**`src/validators/`:**
- Purpose: Business rule validation
- Key file: `validator.py` (286 lines) — `Validator` class with field/decimal/date/status/duplicate checks

**`src/pipeline/`:**
- Purpose: Ingestion orchestrator
- Key file: `ingestion_pipeline.py` (504 lines) — `IngestionPipeline` with `process_file()` method

**`src/reconciliation/`:**
- Purpose: Transaction matching engine
- Key files: `engine.py` (460 lines) — `ReconciliationEngine` with `reconcile()` method; `scope.py` (81 lines) — scope classification

**`src/fetchers/`:**
- Purpose: Data retrieval from external sources
- Contains: `base.py` (174 lines) — `BaseFetcher` ABC with credential resolution, date interpolation; `sftp_fetcher.py`, `api_fetcher.py`, `filedrop_fetcher.py`

**`src/scheduler/`:**
- Purpose: Cron-based job scheduling
- Key files: `scheduler.py` (223 lines) — `PartnerDataScheduler` wrapping APScheduler; `config.py` (30 lines); `jobs.py`

**`src/analysis/`:**
- Purpose: AI-powered insight generation
- Contains: `insights.py` (1088 lines) — orchestration; `provider.py` — AIProviderRouter with fallback; `providers/openai_compat.py` — OpenAI-compatible LLM client; `schemas.py` — AnalysisInput, AnalysisResult, SummaryResult; `metrics.py` — MetricsService; `grouping.py` — GroupingEngine; `guardrails.py` — insight validation; `cache.py` — TTL caching; `prompts.py` — prompt templates; `services.py` — input building; `alerter.py` — threshold alerts; `reporter.py` — daily reports; `config.py` — analysis settings

**`src/api/`:**
- Purpose: FastAPI HTTP layer
- Contains: `__init__.py` (95 lines) — factory + lifespan; 11 router files — `insights.py`, `reconciliation.py`, `data_explorer.py`, `mappings.py`, `copilot.py`, `operations.py`, `review_packets.py`, `automation.py`, `audit.py`, `actor.py`; `response_utils.py` — camelCase JSON serialization
- Routers registered with prefix patterns; all follow `APIRouter(prefix="/api/v1/...")`

**`src/services/`:**
- Purpose: Thin business logic helpers
- Contains: `audit.py` (25 lines), `runtime_runs.py` (91 lines), `runtime_validation.py`, `mapping_contract.py`, `review_packet_actions.py`, `ai_mapping_context.py`, `copilot_context.py`

**`src/logging/`:**
- Purpose: Structured event-driven logging
- Key file: `logger.py` (213 lines) — `StructuredLogger` with 5 event types, JSON/Text formatters, thread-safe singleton

**`frontend-next/src/app/`:**
- Purpose: Next.js App Router pages
- Contains: `layout.tsx` (root layout with AppShell + ToastProvider), `page.tsx` (redirects to /review-center), `reconciliation/page.tsx` (581 lines), `review-center/page.tsx`, `schedules/page.tsx`, `mapping-studio/page.tsx`, `audit-log/page.tsx`

**`frontend-next/src/components/`:**
- Purpose: React components organized by domain
- Contains: `ui/` (Button, Badge, Panel, Dialog, Toast, MetricCard, PageHeader, PageSection), `layout/` (AppShell, AppSidebar, Topbar), `reconciliation/` (EvidenceTable, InsightGrid, RunStatusPanel, SummaryStrip, BulkActionBar, PaginationBar, BatchReviewDialog, EvidenceDetailDialog, InsightExplainDialog, ReconciliationSkeleton), `review-center/` (GuidedReviewModal, ReviewPacketCard, ReviewSummaryDrawer, guided-review-* steps, use-* hooks), `mapping-studio/` (MappingStudioWizard, MappingConfigsTable, PendingActionsList, wizard steps), `schedules/` (ScheduleTable, RecentPacketsGrid), `audit/` (AuditTable, AuditDetailDialog)

**`frontend-next/src/lib/`:**
- Purpose: Frontend business logic
- Contains: `api/` (client.ts — base HTTP, reconciliation.ts, review-center.ts, mapping-studio.ts, audit.ts, automation.ts, review-center-normalizer.ts), `state/` (reconciliation-store.ts — useReconciliationStore hook, mock-*.ts data files), `actor.ts` (X-Actor header management), `review-runtime.ts`, `review-runtime-validation.ts`

**`frontend-next/src/types/`:**
- Purpose: TypeScript type definitions
- Contains: `api.ts` (ApiResponse, ApiError), `reconciliation.ts` (ReconciliationRow, ReconciliationStats, InsightItem, ReconciliationPageState, ReviewRecord), `mapping.ts`, `review-center.ts`, `schedules.ts`, `audit.ts`

**`tests/`:**
- Purpose: pytest test suite (48 entries)
- Contains: Per-module test files mirroring `src/` structure — `test_normalizer.py`, `test_reconciliation.py`, `test_ingestion_pipeline.py`, `test_validator.py`, `test_*_reader.py`, `test_config_*.py`, `test_api_*.py`, `test_analysis_*.py`, `test_models.py`, `test_logger.py`, integration tests (`test_ingestion_integration.py`, `test_analysis_e2e.py`, `test_seed_momo_e2e.py`), `conftest.py` with shared fixtures

## Key File Locations

**Entry Points:**
- `run.py` — Main CLI entry: ingestion, reconciliation, scheduler, server
- `src/api/__init__.py` — FastAPI factory: `create_app()`
- `frontend-next/src/app/layout.tsx` — Next.js root layout
- `frontend-next/src/app/page.tsx` — Home page (redirects to /review-center)

**Configuration:**
- `src/config/settings.py` — `Settings` pydantic model from env vars (`APP_` prefix)
- `pyproject.toml` — Python project config, dependencies, tool settings
- `frontend-next/package.json` — Frontend dependencies and scripts
- `.env` — Environment variables (not committed)
- `.env.example` — Environment variable template

**Core Logic:**
- `src/pipeline/ingestion_pipeline.py` — File ingestion orchestrator (504 lines)
- `src/normalizer/normalizer.py` — Field mapping normalization (520 lines)
- `src/validators/validator.py` — Business rule validation (286 lines)
- `src/reconciliation/engine.py` — Transaction matching engine (460 lines)
- `src/analysis/insights.py` — AI insight orchestration (1088 lines)
- `src/readers/excel_reader.py` — Excel streaming parser
- `src/readers/csv_reader.py` — CSV streaming parser
- `src/readers/json_reader.py` — JSON streaming parser

**Models:**
- `src/models/repository.py` — `BaseRepository[T]` generic (122 lines)
- `src/models/data_container.py` — `DataContainer` + `DataContainerRepository` (161 lines)
- `src/models/mapping_config.py` — `MappingConfig` + `MappingConfigRepository` (167 lines)
- `src/models/reconciliation_result.py` — `ReconciliationResult` + `ReconciliationResultRepository` (160 lines)
- `src/models/indexes.py` — MongoDB index definitions (184 lines)

**API Routers:**
- `src/api/insights.py` — AI analysis endpoints (444 lines)
- `src/api/reconciliation.py` — Reconciliation endpoints (748 lines)
- `src/api/mappings.py` — Mapping config CRUD endpoints
- `src/api/review_packets.py` — Review packet endpoints
- `src/api/copilot.py` — AI copilot endpoints
- `src/api/automation.py` — Automation run endpoints
- `src/api/data_explorer.py` — Data exploration endpoints
- `src/api/operations.py` — Operations endpoints
- `src/api/audit.py` — Audit log endpoints

**Testing:**
- `tests/conftest.py` — Shared test fixtures
- `tests/test_ingestion_integration.py` — End-to-end ingestion test
- `tests/test_reconciliation.py` — Reconciliation engine tests
- `tests/test_analysis_*.py` — Analysis layer tests (12 files)
- `tests/test_api_*.py` — API endpoint tests (8 files)
- `tests/test_normalizer.py` — Normalizer unit tests
- `tests/test_validator.py` — Validator unit tests

## Naming Conventions

**Python Files:**
- Snake case: `ingestion_pipeline.py`, `mapping_config.py`, `data_container.py`, `sftp_fetcher.py`, `error_formatting.py`
- One primary class per file, file name matches class (snake_case version)

**TypeScript/React Files:**
- kebab-case for component files: `app-shell.tsx`, `review-packet-card.tsx`, `insight-explain-dialog.tsx`, `batch-review-dialog.tsx`
- Hyphenated path segments in `app/` directory match Next.js route structure

**Directories:**
- Python: One-word short names inside `src/` — `core/`, `config/`, `models/`, `api/`, `pipeline/`, `analysis/`
- Frontend: Domain grouping — `ui/`, `layout/`, `reconciliation/`, `review-center/`, `mapping-studio/`, `schedules/`, `audit/`
- API route modules inside `api/` — single word matching domain: `insights.py`, `reconciliation.py`, `mappings.py`

**Classes (Python):**
- PascalCase for classes: `IngestionPipeline`, `ReconciliationEngine`, `TransactionNormalizer`, `ConfigLoader`, `BaseRepository`, `DataContainer`, `MappingConfig`
- Repository class names match their model: `DataContainerRepository`, `MappingConfigRepository`, `ReconciliationResultRepository`

**Types (TypeScript):**
- PascalCase for interfaces: `ReconciliationPageState`, `ReconciliationRow`, `InsightItem`, `ReconciliationStats`, `ReviewRecord`, `ApiResponse`

**Functions (Python):**
- Snake case: `process_file()`, `load_by_partner_type()`, `get_summary()`, `classify_scope()`, `record_audit_event()`

**Functions (TypeScript):**
- camelCase: `getRunStatus()`, `runReconciliation()`, `addReviewNote()`, `normalizeInsight()`, `toggleRow()`

**Database Collections:**
- Snake_case prefixed: `reconciliation_file`, `reconciliation_mapping_config`, `reconciliation_result`, `data_container`, `internal_transaction`, `audit_event`, `copilot_action`

## Where to Add New Code

**New Python Module:**
- If in a domain that already exists: add file to that directory (e.g., new analysis feature → `src/analysis/`)
- If new domain: create `src/<domain>/` with `__init__.py`
- Add model + repository paired in `src/models/<name>.py`
- Add FastAPI router in `src/api/<name>.py` and register in `src/api/__init__.py`

**New API Endpoint:**
- Add route to existing router in `src/api/<domain>.py` or create new router file
- Register new router in `src/api/__init__.py:create_app()`
- Add frontend API function in `frontend-next/src/lib/api/<domain>.ts`
- Use existing `client.ts` `get<T>()` / `post<T>()` helpers

**New Frontend Page:**
- Create directory at `frontend-next/src/app/<page-name>/`
- Add `page.tsx` as client component with `"use client"` directive
- Add components in `frontend-next/src/components/<domain>/`
- Add state hook in `frontend-next/src/lib/state/` if needed
- Add type definitions in `frontend-next/src/types/<domain>.ts`

**New Frontend Component:**
- Domain component → `frontend-next/src/components/<domain>/<component-name>.tsx`
- Shared UI component → `frontend-next/src/components/ui/<component-name>.tsx`
- Use CSS modules: `<component-name>.module.css` in same directory

**New Feature (Full Stack):**
1. Models + Repositories: `src/models/<name>.py`
2. API Router: `src/api/<name>.py` + register in factory
3. API test: `tests/test_api_<name>.py`
4. Frontend types: `frontend-next/src/types/<domain>.ts`
5. Frontend API: `frontend-next/src/lib/api/<domain>.ts`
6. Frontend components: `frontend-next/src/components/<domain>/`
7. Frontend state: `frontend-next/src/lib/state/<domain>-store.ts`
8. Frontend page: `frontend-next/src/app/<page-name>/page.tsx`

**New Test:**
- Unit test: `tests/test_<module>.py` — mirrors `src/<module>/` structure
- Integration test: `tests/test_<feature>_integration.py` or `test_<feature>_e2e.py`
- Add shared fixtures to `tests/conftest.py`

## Special Directories

**`.agents/`:**
- Purpose: AI agent skills and configuration
- Generated: No
- Committed: Yes

**`.planning/`:**
- Purpose: Project planning documents and codebase analysis
- Generated: Yes (by GSD commands)
- Committed: Yes

**`mock_data/`:**
- Purpose: Test fixture files (Excel, CSV) for development and testing
- Generated: No
- Committed: Yes

**`sftp_data/`:**
- Purpose: Local fallback data for SFTP fetcher when SFTP server unavailable
- Generated: No
- Committed: Yes

**`tmp_downloads/`, `scratch/`:**
- Purpose: Runtime temporary directories for file downloads and uploads
- Generated: Yes (runtime)
- Committed: No (gitignored)

**`dist/`:**
- Purpose: Build artifacts
- Generated: Yes (build)
- Committed: No (gitignored)

---

*Structure analysis: 2026-06-23*
