# Data Flow

## Primary Flows

The codebase currently centers around four operational flows:

1. ingestion
2. reconciliation
3. approval-driven mapping review
4. scheduled automation

## 1. Ingestion Flow

Main entrypoints:

- `run.py`
- `src/pipeline/ingestion_pipeline.py`

Flow:

1. Accept a local file path or a file retrieved through scheduler/fetch flow.
2. Compute file hash and check duplicate ingestion.
3. Create a `reconciliation_file` tracking record.
4. Load mapping config via `ConfigLoader`.
5. Read rows through the configured reader.
6. Normalize rows into canonical transactions.
7. Validate canonical transactions.
8. Persist valid rows into `data_container`.
9. Update file stats and final processing state.

## 2. Reconciliation Flow

Main entrypoints:

- `run.py --reconcile ...`
- `src/reconciliation/engine.py`
- `/api/v1/reconciliation/*`

Flow:

1. Load canonical partner-side data from `data_container`.
2. Load internal transactions from `internal_transaction`.
3. Match records using reconciliation logic.
4. Persist classified outcomes into `reconciliation_result`.
5. Expose results, stats, and analysis through the API.

## 3. Review Packet and Mapping Approval Flow

Main entrypoints:

- `src/api/mappings.py`
- `src/api/review_packets.py`
- `src/config/config_health.py`

Flow:

1. A mapping proposal is generated or uploaded.
2. A `review_packet` and optionally a `copilot_action` are created.
3. Reviewers inspect packet details through the dashboard or API.
4. Review action is applied:
   - approve and activate next runtime
   - approve and keep current runtime
   - reject
   - send to mapping studio
5. Mapping and review status are synchronized across related documents.

## 4. Automation Flow

Main entrypoints:

- `src/scheduler/jobs.py`
- `src/api/automation.py`
- `src/fetchers/`

Flow:

1. Scheduler loads enabled `fetch_config` records.
2. The correct fetcher is created for the configured method.
3. The file is fetched or an error is recorded.
4. On success, ingestion runs against the fetched file.
5. Results are surfaced through automation visibility endpoints and the dashboard.

## Dashboard Context Flow

Main entrypoints:

- `src/services/copilot_context.py`
- `src/api/copilot.py`

Flow:

1. Dashboard requests Copilot context for a partner, date, screen, or file.
2. Service aggregates review packet, mapping, file, and automation state.
3. API returns a context object plus action references.
4. Dashboard can execute supported Copilot actions against review or mapping flows.

## Practical Note

Older docs in this repo tended to mix implemented flows with planned behavior. When updating this file, prefer describing only the path that can be traced through the current modules and routes.
