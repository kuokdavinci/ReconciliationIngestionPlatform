# Module Map

## Backend Packages

### `src/core`

Shared enums, constants, and canonical types.

### `src/config`

Runtime settings, mapping config loading/validation, cache, signatures, config-health workflows, and AI mapping generation helpers.

### `src/readers`

Input readers for Excel, CSV, and JSON sources.

### `src/normalizer`

Transforms raw source rows into canonical field values.

### `src/validators`

Canonical transaction validation and duplicate checks.

### `src/models`

MongoDB-backed domain models, repositories, and index definitions.

Important models in active flows:

- `mapping_config`
- `reconciliation_file`
- `data_container`
- `internal_transaction`
- `reconciliation_result`
- `review_packet`
- `copilot_action`
- `fetch_config`

### `src/pipeline`

Ingestion orchestration.

### `src/reconciliation`

Matching and classification logic for partner vs internal records.

### `src/api`

FastAPI routers for:

- insights and reports
- reconciliation
- data explorer
- mappings
- Copilot context/actions
- operations intake
- review packets
- automation

### `src/analysis`

Insight generation, provider abstraction, schemas, prompts, and reporting.

### `src/services`

Higher-level services used by APIs, currently including Copilot context assembly.

### `src/scheduler`

Scheduler setup and job execution for automated partner fetch flows.

### `src/fetchers`

Fetcher implementations and method-specific remote input handling.

### `src/logging`

Structured logging helpers.

## Frontend

### `frontend/app.js`

Main SPA logic, route rendering, state handling, and API calls.

### `frontend/index.html`

Dashboard shell.

### `frontend/styles.css`

Dashboard styling.

### `frontend/vite.config.js`

Vite dev server and `/api` proxy configuration.
