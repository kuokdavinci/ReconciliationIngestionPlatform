# Configuration

## Sources of Truth

Application settings are defined in:

- `src/config/settings.py` for `APP_` variables
- `src/analysis/config.py` for `AI_` variables
- `.env.example` for local bootstrap values
- `docker-compose.yml` for container wiring overrides

## Application Settings

Loaded by `src/config/settings.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `APP_DB_NAME` | `reconciliation` | Database name |
| `APP_POSTGRES_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation` | PostgreSQL connection string (asyncpg) |
| `APP_LOG_LEVEL` | `INFO` | Log level |
| `APP_LOG_FORMAT` | `json` | Log output format |
| `APP_APP_NAME` | `reconciliation-ingestion` | Service name |
| `APP_STRICT_MAPPING_APPROVAL_ENABLED` | `true` | Controls strict mapping approval behavior in runtime settings |
| `APP_UPLOAD_TMP_DIR` | `./scratch/temp_uploads` | Temporary upload directory |
| `APP_INGEST_BATCH_SIZE` | `20000` | Ingestion MongoDB batch insert size |
| `APP_INGEST_WRITE_WORKERS` | `2` | Parallel write workers for ingestion |
| `APP_INGEST_ORDERED_INSERT` | `false` | Ordered vs unordered MongoDB inserts during ingestion |
| `APP_RECON_PARTNER_BATCH_SIZE` | `10000` | Partner record batch size for reconciliation streaming |
| `APP_RECON_RESULT_BATCH_SIZE` | `20000` | Result write batch size for reconciliation |
| `APP_RECON_RESULT_WRITE_WORKERS` | `2` | Parallel write workers for reconciliation results |
| `APP_RECON_RESULT_ORDERED_INSERT` | `false` | Ordered vs unordered MongoDB inserts for reconciliation results |

The `Settings` class in `src/config/settings.py` (40 lines) has been extended with PostgreSQL URL and performance tuning configurations.

## AI Analysis Settings

Loaded by `src/analysis/config.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `AI_PROVIDER` | `openai` | Primary LLM provider (`openai | ollama`) |
| `AI_MODEL` | `gpt-4o` | Primary model |
| `AI_ENDPOINT` | `https://api.openai.com/v1` | Primary endpoint |
| `AI_API_KEY` | none | Primary provider credential |
| `AI_FALLBACK_PROVIDER` | `openai` | Fallback provider |
| `AI_FALLBACK_MODEL` | `gpt-4o-mini` | Fallback model |
| `AI_FALLBACK_ENDPOINT` | none | Fallback endpoint, defaults to primary if unset |
| `AI_FALLBACK_API_KEY` | none | Fallback API key, defaults to primary if unset |
| `AI_TIMEOUT` | `30` | Request timeout in seconds |
| `AI_MAX_RETRIES` | `2` | Retry attempts |
| `AI_JSON_MODE` | `true` | Structured response mode toggle |
| `AI_CACHE_TTL_SECONDS` | `300` | Insight cache TTL |
| `AI_CACHE_ENABLED` | `true` | In-memory insight cache toggle |
| `AI_ALERT_MISMATCH_RATE_THRESHOLD` | `5.0` | Alert threshold |
| `AI_ALERT_MISSING_COUNT_THRESHOLD` | `10` | Alert threshold |

No new AI env vars have been added. The `AnalysisConfig` class in `src/analysis/config.py` (93 lines) remains stable.

## Local Bootstrap

Create local config:

```bash
cp .env.example .env
```

`.env.example` currently also carries local Docker/SFTP bootstrap values:

- `MONGO_ROOT_USER`
- `MONGO_ROOT_PASSWORD`
- `SFTP_HOST`
- `SFTP_PORT`
- `SFTP_USER`
- `SFTP_PASS`
- `SFTP_REMOTE_DIR`

These are not loaded by `BaseSettings` directly unless referenced by code or container config, but they are part of the local runtime contract.

**Note on drift:** `.env.example` uses `AI_MODEL=gpt-4o-mini`, while `AnalysisConfig` defaults to `gpt-4o`. Treat the effective value as environment-driven when `.env` is used.

## Docker Overrides

`docker-compose.yml` overrides or wires:

- `APP_MONGODB_URL` for `api` and `scheduler`
- `APP_POSTGRES_URL` pointing to the `postgres` service for `api` and `scheduler`
- `SFTP_HOST=sftp` for the scheduler container
- MongoDB root credentials for the database and Mongo Express

## Mapping Configuration Lifecycle

Runtime mapping configs live in MongoDB and are loaded through `ConfigLoader`.

Relevant modules:

- `src/config/loader.py` — orchestrates config loading from MongoDB with caching and validation
- `src/config/validator.py` — field mapping integrity checks
- `src/config/cache.py` — TTL in-memory config caching
- `src/config/signature.py` — file structure signature computation for drift detection
- `src/config/ai_generator.py` — AI-powered MappingConfig generation from sample data (uses LLM via `AnalysisConfig`)
- `src/config/config_health.py` — config health detection that creates approval-gated proposals
- `src/models/mapping_config.py`

Supported states:

- `PENDING_APPROVAL`
- `APPROVED`
- `REJECTED`
- `SUPERSEDED`

Only approved configs are intended for active runtime loading.

**AI Config Generator** (`src/config/ai_generator.py`):
- Accepts partner name, headers, sample rows, and known constants.
- Uses `AnalysisConfig` + `create_provider()` to invoke LLM.
- Returns a structured MappingConfig dict with `startRow`, `fieldMappings`, `confidence`, and `reasoning`.
- Has explicit Vietnamese language support in status detection (Thành công, Thất bại, Đang xử lý, Đã hoàn tác).
- Used by both `config_health.py` (automated drift detection) and `review_packets.py` (manual AI generation button).

## Mapping Contract Service

`src/services/mapping_contract.py` acts as a configuration validation layer for field mappings entering the system through review packets or the Copilot flow.

Key exports:

- `serialize_field_mappings(raw_mappings)` — converts Pydantic/dict mappings to uniform dict list
- `canonicalize_field_mappings(raw_mappings)` — normalizes mappings:
  - Injects `currency` as `CONSTANT "VND"` if not mapped
  - Upgrades `status` from `STRING` to `MAPPING` with Vietnamese-aware defaults
  - Returns warnings for any adjustments made
- `validate_mapping_contract(config, required_paths)` — validates a `MappingConfig`:
  - Runs `ConfigValidator.validate()` and `ConfigValidator.validate_required_coverage()`
  - Detects columns mapped to multiple fields
  - Detects fields with neither source column nor constant value
  - Returns `MappingContractValidation` with `errors`, `warnings`, and a numeric `score`

This is invoked by `src/api/review_packets.py` on every `save-draft-mapping` call and by `src/api/copilot.py` for Copilot-generated proposals.

## Review, Automation, and Run Tracking Documents

Additional persisted configuration-like documents:

- `review_packet`
  - human review state for mapping/runtime changes
- `copilot_action`
  - Copilot recommendation audit trail
- `fetch_config`
  - partner fetch method and schedule definitions (SFTP, API, FileDrop)
  - `src/models/fetch_config.py` — model with three method configs + repository
- `partner_runtime_run`
  - unified runtime visibility for fetch → ingest → reconcile flows
  - collection: `partner_runtime_run`
  - trigger types: `SCHEDULER`, `MANUAL_RECONCILIATION`, `POST_APPROVAL_REPROCESS`
  - statuses: `QUEUED → FETCHING → INGESTING → WAITING_RECONCILE → RECONCILING → COMPLETED/FAILED`
  - `src/models/partner_runtime_run.py`, `src/services/runtime_runs.py`
- `post_approval_run`
  - tracking for long-running reprocess + reconcile after mapping approval
  - collection: `post_approval_run`
  - stages: `approval → ingestion → reconciliation → cache_invalidation`
  - `src/models/post_approval_run.py`
- `reconciliation_run`
  - manual reconciliation run tracking for UI-triggered execution
  - collection: `reconciliation_run`
  - statuses: `QUEUED → RUNNING → COMPLETED/FAILED`
  - `src/models/reconciliation_run.py`
- `reconciliation_review_record`
  - per-record review notes and resolution state
  - collection: `reconciliation_review_record`
  - `src/models/reconciliation_review_record.py`

## Index Configuration

MongoDB indexes are defined centrally in `src/models/indexes.py` and applied on application startup via `apply_indexes()`.

| Collection | Indexes | Purpose |
|---|---|---|
| `reconciliation_file` | `fileHash` (unique), `partner+reconciliationDate` | Duplicate prevention & partner/date queries |
| `reconciliation_mapping_config` | `partner+workflowType+fileType`, unique partial `partner+workflowType+fileType+status` (where `APPROVED`) | Config lookup & single-approved constraint |
| `copilot_action` | `status+type+partner` | Copilot action filtering |
| `review_packet` | `status+partner+createdAt`, `draftMappingId` | Packet listing & mapping lookup |
| `data_container` | `partnerData.trace`, `identify+reconciliationDate`, `operationStatus`, `partnerData.status`, `sourceFileId` | Reconciliation & filtering |
| `internal_transaction` | `partnerTxnId`, `partner+transactionTime` | Reconciliation key lookup |
| `reconciliation_result` | `partner+date+_id`, `partner+date+reconciliationStatus+_id`, `partnerTxnId`, `reconciliationStatus` | Pagination, filtering, stats |
| `post_approval_run` | `packetId+createdAt`, `status+updatedAt` | Post-approval tracking |
| `partner_runtime_run` | `partner+date+createdAt`, `status+updatedAt` | Run visibility |
| `reconciliation_run` | `partner+date+createdAt` | Manual run tracking |
| `reconciliation_review_record` | `partner+date+recordKey` (unique) | Review record lookup |

## PostgreSQL Database

The platform supports PostgreSQL for transactional data storage alongside MongoDB. The PostgreSQL instance is defined in `docker-compose.yml` and initialized via `src/models/postgres.py`.

### Tables

| Table | Purpose |
|-------|---------|
| `partner_transaction` | Partner canonical records from ingestion (UNLOGGED for performance) |
| `internal_transaction` | Internal/backend transaction records (UNLOGGED for performance) |
| `reconciliation_result` | Reconciliation match/mismatch results |

### Performance Optimization

PostgreSQL tables `partner_transaction` and `internal_transaction` are created as `UNLOGGED` tables to bypass WAL write-ahead logging, reducing disk I/O during bulk ingestion. This is safe because these tables are staging/transactional data that can be rebuilt from source files.

In-database reconciliation uses SQL joins (`INSERT ... SELECT ... LEFT JOIN` with `CASE WHEN`) instead of Python in-memory matching, achieving ~3x speedup over the MongoDB path (see [INGEST_RECON_TRACE.md](INGEST_RECON_TRACE.md)).

### PostgreSQL Env Vars

- `APP_POSTGRES_URL` — Connection string (default: `postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation`)

## Notes on Drift

- Keep docs synchronized with settings classes first, then with example env files.
- `partner_runtime_run` and `post_approval_run` collections overlap in purpose — `partner_runtime_run` is the unified tracking model while `post_approval_run` is specific to the post-approval reprocess flow. Both should be kept consistent in status semantics.
- `reconciliation_run` (`src/models/reconciliation_run.py`) is a lightweight run tracker distinct from `partner_runtime_run` — it only tracks manually triggered reconciliation runs without the fetch/ingest stages.
- PostgreSQL is used for bulk transactional processing (ingestion + reconciliation); MongoDB remains the source of truth for mapping configs, review packets, fetch configs, and audit events.
