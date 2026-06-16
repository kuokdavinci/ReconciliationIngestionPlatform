# Module Map

**Cập nhật lần cuối:** 2026-06-16

## Backend Packages

### `src/core`

Shared enums, constants, canonical types, và error formatting.

**Files:**
- `enums.py` — `ProcessingStatus`, `TransactionStatus`, `FileType`, `ReconciliationStatus`, `ReconciliationScopeType`
- `types.py` — `FieldMapping`, `CanonicalTransaction`, `PartnerData`, `ValidationError`, `ProcessingStats`
- `constants.py` — `DEFAULT_CURRENCY`, `FILE_HASH_KEY`, duplicate key patterns
- `error_formatting.py` — `summarize_runtime_error` helper cho UI-safe error messages

### `src/config`

Runtime settings, mapping config loading/validation, cache, signatures, config-health workflows, AI mapping generation.

**Files:**
- `settings.py` — Runtime settings via pydantic-settings
- `loader.py` — Config loader from MongoDB
- `validator.py` — Config validation rules
- `cache.py` — Config caching layer
- `signature.py` — File structure signature computation
- `config_health.py` — Config health check workflows
- `ai_generator.py` — AI-powered mapping generation from samples

### `src/readers`

Input readers cho Excel, CSV, và JSON sources.

**Files:**
- `excel_reader.py`
- `csv_reader.py`
- `json_reader.py`

### `src/normalizer`

Transform raw source rows thành canonical field values.

**Files:**
- `normalizer.py` — `TransactionNormalizer` class

### `src/validators`

Canonical transaction validation và duplicate checks.

**Files:**
- `validator.py`

### `src/models`

MongoDB-backed domain models, repositories, và index definitions.

**Files:**

| Model file | Collection | Purpose |
|---|---|---|
| `reconciliation_file.py` | `reconciliation_file` | File metadata và processing status |
| `data_container.py` | `data_container` | Partner canonical records |
| `internal_transaction.py` | `internal_transaction` | Internal transaction records |
| `reconciliation_result.py` | `reconciliation_result` | Reconciliation match/mismatch results |
| `mapping_config.py` | `reconciliation_mapping_config` | Field mapping configs (approved + pending) |
| `review_packet.py` | `review_packet` | Review packets cho approval workflows |
| `copilot_action.py` | `copilot_action` | Copilot action tracking |
| `fetch_config.py` | `fetch_config` | Automation fetch configuration |
| `reconciliation_run.py` | `reconciliation_run` | Manual reconciliation run tracking |
| `post_approval_run.py` | `post_approval_run` | Post-approval reprocess tracking |
| `partner_runtime_run.py` | `partner_runtime_run` | Unified runtime visibility (scheduler/manual/post-approval) |
| `reconciliation_review_record.py` | `reconciliation_review_record` | Review notes và resolution state per record |
| `repository.py` | — | Base repository class (`BaseRepository`) |
| `indexes.py` | — | MongoDB index definitions và startup creation |

### `src/pipeline`

Ingestion orchestration.

**Files:**
- `ingestion_pipeline.py` — `IngestionPipeline` class

### `src/reconciliation`

Matching và classification logic cho partner vs internal records.

**Files:**
- `engine.py` — `ReconciliationEngine` với streaming, batch scope resolution, và buffered writes
- `scope.py` — Scope classification helpers qua filename hints và same-day file count

### `src/api`

FastAPI routers.

**Routers:**

| Module file | Prefix | Endpoints |
|---|---|---|
| `insights.py` | `/api/v1` | `/insights/summary`, `/insights/discrepancies`, `/reports/daily` |
| `reconciliation.py` | `/api/v1/reconciliation` | Reconciliation execute, results, review notes, run tracking |
| `data_explorer.py` | `/api/v1/data` | Data browsing và filtering |
| `mappings.py` | `/api/v1/mappings` | Mapping config CRUD, proposals, file upload |
| `mappings.py` (router_v2) | `/api/v1/mapping` | Short-form mapping operations |
| `copilot.py` | `/api/v1/copilot` | Context assembly và action proxies |
| `operations.py` | `/api/v1/operations` | Intake status, approval overview |
| `review_packets.py` | `/api/v1/review-packets` | Review lifecycle: approve-activate, approve-keep-current, reject, send-to-studio, runtime validation, AI generation, scope |
| `automation.py` | `/api/v1/automation` | Scheduler visibility, run-now, fetch config management |

### `src/analysis`

Insight generation, provider abstraction, schemas, prompts, reporting, caching, alerting.

**Files:**
- `config.py`, `provider.py`, `schemas.py`, `insights.py`, `prompts.py`, `services.py`
- `metrics.py`, `grouping.py`, `reporter.py`, `cache.py`, `alerter.py`, `guardrails.py`

### `src/services`

Higher-level services used bởi APIs.

**Files:**

| File | Trách nhiệm |
|---|---|
| `copilot_context.py` | Rule-based Copilot context assembly cho dashboard (intake/review/reconciliation/automation screens) |
| `mapping_contract.py` | Mapping contract normalization (`canonicalize_field_mappings`, `serialize_field_mappings`), validation (`validate_mapping_contract`, `MappingContractValidation`) |
| `review_packet_actions.py` | Shared review packet approval actions (`approve_packet_mapping_and_reprocess`, `mark_packet`, `reprocess_and_reconcile`), post-approval run tracking, background task management |
| `runtime_runs.py` | Unified runtime run visibility helpers (`create_runtime_run`, `update_runtime_run`, `serialize_partner_runtime_run`) |

### `src/scheduler`

Scheduler setup và job execution cho automated partner fetch flows.

**Files:**
- `config.py`, `scheduler.py`, `jobs.py`

### `src/fetchers`

Fetcher implementations và method-specific remote input handling.

**Files:**
- `base.py`, `sftp_fetcher.py`, `filedrop_fetcher.py`, `api_fetcher.py`

### `src/logging`

Structured logging helpers.

**Files:**
- `logger.py` — Structured logger factory

## Frontend

### `frontend/`

**Files:**

| File | Purpose |
|---|---|
| `app.js` | Main SPA logic, route rendering, state handling, API calls (Command Center, Data Intake, Review Center, Reconciliation, Mapping Studio, Automation) |
| `index.html` | Dashboard shell |
| `styles.css` | Dashboard styling |
| `vite.config.js` | Vite dev server config, `/api` proxy tới `http://localhost:8000`, build config |
| `package.json` | npm scripts (`dev`, `build`, `preview`), dependency: `vite ^5.0.0` |
| `server.py` | Optional Python static server |

---

*Module analysis: 2026-06-16*
