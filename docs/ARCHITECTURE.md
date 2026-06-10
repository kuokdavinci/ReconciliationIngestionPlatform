# Architecture

## Overview

The platform ingests partner files into canonical transaction records, compares them with internal transactions, and exposes review and operations workflows over FastAPI. Mapping changes are approval-driven and persisted in MongoDB.

## Main Runtime Pieces

- `run.py`
  - CLI entrypoint for serving the API, running ingestion, controlling the scheduler, and running reconciliation
- `src.api:create_app`
  - FastAPI app factory with MongoDB lifespan management and router registration
- `frontend/`
  - Vite-served Vanilla JS dashboard that talks to the backend through `/api`

## Backend Subsystems

### Ingestion

- `src/pipeline/ingestion_pipeline.py`
- `src/readers/`
- `src/normalizer/`
- `src/validators/`
- `src/config/loader.py`

Responsibilities:

- compute file hash
- detect duplicate files
- load and validate mapping config
- read source rows
- normalize and validate canonical transactions
- persist file metadata and canonical records

### Reconciliation

- `src/reconciliation/engine.py`
- `src/models/internal_transaction.py`
- `src/models/reconciliation_result.py`

Responsibilities:

- compare partner-side canonical data with internal transactions
- classify result status
- persist reconciliation results for API and dashboard consumption

### Approval and Mapping Lifecycle

- `src/api/mappings.py`
- `src/api/review_packets.py`
- `src/models/mapping_config.py`
- `src/models/review_packet.py`
- `src/models/copilot_action.py`
- `src/config/config_health.py`

Responsibilities:

- create or review mapping proposals
- keep approved runtime mappings separate from pending proposals
- track review packets and Copilot actions
- support approve-activate, approve-keep-current, reject, and studio handoff flows

### Automation

- `src/scheduler/`
- `src/fetchers/`
- `src/api/automation.py`

Responsibilities:

- load enabled fetch configs
- fetch partner files via configured method
- run ingestion
- expose automation visibility and run-now control

### AI-Assisted Analysis

- `src/analysis/`
- `src/api/insights.py`
- `src/api/reconciliation.py`
- `src/services/copilot_context.py`

Responsibilities:

- summarize reconciliation outcomes
- generate discrepancy views and daily reports
- provide contextual Copilot guidance for dashboard screens

## Request Surface

The API currently registers these router groups:

- `/api/v1/insights`
- `/api/v1/reports`
- `/api/v1/reconciliation`
- `/api/v1/data`
- `/api/v1/mappings`
- `/api/v1/mapping`
- `/api/v1/copilot`
- `/api/v1/operations`
- `/api/v1/review-packets`
- `/api/v1/automation`

## Data Stores

MongoDB is the only primary persistence store currently configured in runtime code. Important collections include:

- `reconciliation_file`
- `data_container`
- `internal_transaction`
- `reconciliation_result`
- `reconciliation_mapping_config`
- `review_packet`
- `copilot_action`
- `fetch_config`

Indexes are applied at startup by `src/models/indexes.py`.

## Frontend Shape

The dashboard is a small SPA in `frontend/app.js` with these major views:

- Command Center
- Data Intake
- Review Center
- Reconciliation
- Mapping Studio
- Automation

The Vite dev server proxies `/api` to `http://localhost:8000`.

## Operational Notes

- The root README is the canonical startup doc.
- API-serving behavior should be documented from `run.py` and `src/api/__init__.py`, not copied from stale examples.
- Approval-driven mapping behavior is a first-class runtime concept and should not be omitted from architecture descriptions.
