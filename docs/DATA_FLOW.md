# Data Flow

## Primary Flows

The codebase currently centers around six operational flows:

1. ingestion
2. reconciliation
3. approval-driven mapping review
4. scheduled automation
5. post-approval reprocess
6. benchmark / performance analysis

## 1. Ingestion Flow

Main entrypoints:

- `run.py`
- `src/pipeline/ingestion_pipeline.py`

Flow:

1. Accept a local file path or a file retrieved through scheduler/fetch flow.
2. Compute file hash and check duplicate ingestion.
3. Create a `reconciliation_file` tracking record.
4. Load mapping config via `ConfigLoader` (`src/config/loader.py`).
5. Read rows through the configured reader (`src/readers/`).
6. Normalize rows into canonical transactions (`src/normalizer/normalizer.py`).
7. Validate canonical transactions (`src/validators/validator.py`).
8. Persist valid rows into `data_container` (MongoDB) and/or `partner_transaction` via `asyncpg.copy_records_to_table` (PostgreSQL COPY, ~1s for 100k rows).
9. Update file stats and final processing state.

**Structure signature & config health check:**
During ingestion, `src/config/config_health.py:check_and_refresh_config` computes a file structure signature via `src/config/signature.py` and compares it with the approved mapping config. If a drift is detected (stale config), the flow:

1. Generates an AI mapping proposal via `src/config/ai_generator.py:generate_config_from_samples`.
2. Creates a `review_packet` + `copilot_action` to block or warn the operator.
3. Raises `ConfigurationApprovalRequiredError` if strict mode is enabled.

This integrates the AI config generator directly into the ingestion gate.

## 2. Reconciliation Flow

Main entrypoints:

- `run.py --reconcile ...`
- `src/reconciliation/engine.py`
- `/api/v1/reconciliation/*`

Flow:

1. Load canonical partner-side data from `data_container` in **streamed batches** (configurable `PARTNER_BATCH_SIZE = 5000`).
2. Load internal transactions from `internal_transaction` — builds an **in-memory index** keyed by `partnerTxnId`, filtering only finalized statuses (`SUCCESS`, `FAILED`, `REVERSED`).
3. Resolve scope via `ReconciliationScopeType` (`FULL_SNAPSHOT`, `INCREMENTAL_APPEND`, `REPLACEMENT`) stored on the `reconciliation_file`. Non-full scopes restrict partner and internal records to a specific `sourceFileId` and collect scoped partner keys.
4. Pre-check each partner record (`_pre_check_record`) — records with missing amount/status are skipped with `UNMAPPED_SKIPPED` status.
5. Match records using deterministic comparison (amount + status). Results are classified into: `MATCHED`, `MATCHED_FAILED`, `MATCHED_REVERSED`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `MULTIPLE_MISMATCH`, `MISSING_INTERNAL`, `MISSING_PARTNER`.
6. Persist classified outcomes into `reconciliation_result` (MongoDB) in **chunked writes** (batch size `RESULT_WRITE_BATCH_SIZE = 5000`). When PostgreSQL is enabled, reconciliation runs as a SQL `LEFT JOIN` (`INSERT ... SELECT ... LEFT JOIN` with `CASE WHEN`) instead of Python in-memory matching, achieving ~3x speedup (13.4s → 4.6s for 100k records).
7. Expose results, stats, and analysis through the API.

**Reconciliation Run Tracking:**
The API endpoint `POST /api/v1/reconciliation/run` creates a `partner_runtime_run` record via `src/services/runtime_runs.py:create_runtime_run`, runs `ReconciliationEngine.reconcile` in a background `asyncio.Task`, and updates the run status (`QUEUED → RECONCILING → COMPLETED/FAILED`). Run status is queryable via `GET /api/v1/reconciliation/run-status`.

**Review Records:**
The reconciliation API exposes review record endpoints under `/api/v1/reconciliation/review-records`:
- `GET .../review-records` — list review records by partner/date (`src/models/reconciliation_review_record.py`)
- `POST .../review-records/{record_key}/note` — add a review note with upsert semantics
- `POST .../review-records/{record_key}/resolve` — resolve a review record with a status

These are backed by the `reconciliation_review_record` collection and allow operators to annotate and resolve individual reconciliation mismatches.

**AI Insights:**
The API provides LLM-powered reconciliation insights via `GET /api/v1/reconciliation/insights?type=summary|anomalies|patterns|recommendations`. The flow uses:
- `src/analysis/metrics.py` — compute aggregate metrics
- `src/analysis/grouping.py` — group discrepancies
- `src/analysis/provider.py` — LLM provider with fallback chain
- `src/analysis/insights.py` — orchestration with TTL caching

## 3. Review Packet and Mapping Approval Flow

Main entrypoints:

- `src/api/review_packets.py`
- `src/api/mappings.py`
- `src/config/config_health.py`

Flow:

1. A mapping proposal is generated or uploaded. AI-generated proposals now use `src/config/ai_generator.py:generate_config_from_samples` (called from `config_health.py` or from the packet API endpoint `POST /{packet_id}/generate-ai-mapping`).
2. A `review_packet` and optionally a `copilot_action` are created.
3. Reviewers inspect packet details through the dashboard or API.
4. **Runtime validation** can be triggered via `POST /{packet_id}/validate-runtime` — samples up to 20 rows through the proposed mapping, computes a `validationGates` result with `successRate` and `riskLevel`.
5. Review action is applied:
   - **approve and activate next runtime** (`approve_activate_packet_action`) — triggers post-approval reprocess
   - **approve and keep current runtime** (`approve_keep_current_packet_action`)
   - **reject** (`reject_packet_action`)
   - **send to mapping studio** (`send_packet_to_studio`)
6. Mapping and review status are synchronized across related documents.
7. **LLM scope classification** is available via `POST /{packet_id}/classify-scope-llm` — uses the LLM to classify file scope as `FULL_SNAPSHOT`, `INCREMENTAL_APPEND`, or `REPLACEMENT` based on file metadata and internal DB counts.

**Mapping Contract Validation:**
When saving draft mappings via `POST /{packet_id}/save-draft-mapping`, the payload is validated through `src/services/mapping_contract.py`:
- `canonicalize_field_mappings` — normalizes field mappings, injects default `currency` constant and upgrades `status` from STRING to MAPPING if needed.
- `validate_mapping_contract` — runs `ConfigValidator` checks plus column collision detection. Returns structured `MappingContractValidation` with `errors`, `warnings`, and a `score`.

## 4. Automation Flow

Main entrypoints:

- `src/scheduler/jobs.py`
- `src/api/automation.py`
- `src/fetchers/`

Flow:

1. Scheduler loads enabled `fetch_config` records.
2. The correct fetcher is created for the configured method (`SFTP`, `API`, `FILEDROP`).
3. The file is fetched or an error is recorded.
4. On success, ingestion runs against the fetched file.
5. A **`partner_runtime_run`** record is created (trigger type `SCHEDULER`) to track the full fetch → ingest → reconcile lifecycle (see `src/services/runtime_runs.py`).
6. Results are surfaced through automation visibility endpoints (`GET /api/v1/automation/jobs`) and the dashboard.

## 5. Post-Approval Reprocess Flow

Main entrypoints:

- `src/api/review_packets.py` — `approve_activate_packet_action`
- `src/services/review_packet_actions.py` — `approve_packet_mapping_and_reprocess`, `reprocess_and_reconcile`
- `src/models/post_approval_run.py` — `PostApprovalRun`, `PostApprovalRunRepository`

Flow:

1. A reviewer approves a packet with `APPROVE_ACTIVATE_NEXT_RUNTIME` decision.
2. `approve_packet_mapping_and_reprocess` in `src/services/review_packet_actions.py`:
   - Supersedes the current approved mapping config if one exists.
   - Marks the draft mapping as `APPROVED`.
   - Creates a `PostApprovalRun` tracking record (status: `QUEUED`, stage: `approval`).
   - Launches a background `asyncio.Task` for `_run_post_approval_reprocess`.
3. `reprocess_and_reconcile` runs sequentially:
   - **Ingestion stage**: Re-ingests the source file using the newly approved mapping via `IngestionPipeline.process_file`. Updates `PostApprovalRun` to `INGESTING`. On failure, marks run as `FAILED`.
   - **Reconciliation stage**: Runs `ReconciliationEngine.reconcile` against the re-ingested data. Updates `PostApprovalRun` to `RECONCILING`.
   - **Cache invalidation stage**: Invalidates AI insight cache via `invalidate_insight_cache`. Updates `PostApprovalRun` to `COMPLETED`.
4. The `PostApprovalRun` record is queryable via `GET /api/v1/review-packets/{packet_id}/post-approve-run`, exposing status, stage, message, stats, errors, and timing.

**PostApprovalRun** (`src/models/post_approval_run.py`) tracks the full lifecycle:
- Statuses: `QUEUED → INGESTING → RECONCILING → COMPLETED/FAILED`
- Stages: `approval → ingestion → reconciliation → cache_invalidation`

## 6. Benchmark / Performance Analysis Flow

Main files:

- `scripts/benchmark_reconcile_million.py` — seeds 1M synthetic partner rows and compares optimized vs baseline reconciliation paths.
- `reconciliation-flow-benchmark.md` — Vietnamese benchmark report measuring latency for automation status, run status, review records, results pagination, stats, and AI insights on a 100k-row VNPAY dataset.
- `refine-reconciliation-performance.md` — plan documenting the streaming + batch-scope engine refactor, including batching, scope resolution, chunked writes, and post-approval reprocess tracking.

Flow:

1. Run `scripts/benchmark_reconcile_million.py` to seed synthetic data and time key paths.
2. Results are written to `reconciliation_result` (optimized) and `reconciliation_result_baseline_tmp` (baseline) for comparison.
3. Performance findings feed into `refine-reconciliation-performance.md` which documents the engine refactor from fully materialized to streamed partner batches + projected internal query + chunked writes.

## Dashboard Context Flow

Main entrypoints:

- `src/services/copilot_context.py`
- `src/api/copilot.py`

Flow:

1. Dashboard requests Copilot context for a partner, date, screen, or file.
2. Service aggregates review packet, mapping, file, reconciliation result stats, and automation state.
3. API returns a context object plus action references.
4. Dashboard can execute supported Copilot actions against review or mapping flows.
5. Copilot mapping proposals are validated through `src/services/mapping_contract.py` to ensure structured field mappings before being persisted as `copilot_action` documents.

## Practical Note

Older docs in this repo tended to mix implemented flows with planned behavior. When updating this file, prefer describing only the path that can be traced through the current modules and routes.
