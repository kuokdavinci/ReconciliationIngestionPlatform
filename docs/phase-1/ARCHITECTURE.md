# Architecture

**Cập nhật lần cuối:** 2026-06-23

## Tổng quan

Nền tảng tiếp nhận file đối tác, chuẩn hóa thành các bản giao dịch canonical, so sánh với giao dịch nội bộ, và phơi bày quy trình review/vận hành qua FastAPI. Các thay đổi mapping được định hướng theo approval và persisted trong MongoDB.

## Main Runtime Pieces

- `run.py`
  - CLI entrypoint cho serving API, chạy ingestion, điều khiển scheduler, và chạy reconciliation
- `src.api:create_app`
  - FastAPI app factory với MongoDB lifespan management và router registration
- `frontend-next/`
  - Active Next.js + TypeScript dashboard that communicates with FastAPI through `/api`
- `frontend/`
  - Legacy Vite dashboard retained as reference only
- `src/scheduler/scheduler.py:PartnerDataScheduler`
  - APScheduler-based daemon cho partner fetch automation

## Backend Subsystems

### Ingestion

- `src/pipeline/ingestion_pipeline.py`
- `src/readers/`
- `src/normalizer/`
- `src/validators/`
- `src/config/loader.py`

**Responsibilities:**

- compute file hash
- detect duplicate files
- load and validate mapping config
- read source rows
- normalize and validate canonical transactions
- persist file metadata and canonical records

### Reconciliation

- `src/reconciliation/engine.py`
- `src/reconciliation/scope.py`
- `src/models/internal_transaction.py`
- `src/models/reconciliation_result.py`
- `src/models/reconciliation_run.py`
- `src/models/reconciliation_review_record.py`
- `src/services/runtime_runs.py`

**Responsibilities:**

- compare partner-side canonical data with internal transactions
- classify result status (`MATCHED`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `MISSING_INTERNAL`, `MISSING_PARTNER`, etc.)
- triển khai streaming processing qua async generator (`_iter_partner_record_batches`) với batch size mặc định 5000
- hỗ trợ batch scope resolution (`FULL_SNAPSHOT`, `INCREMENTAL_APPEND`, `REPLACEMENT`, `UNCONFIRMED`) qua `src/reconciliation/scope.py`
- tracking reconciliation runs (`reconciliation_run` collection) cho UI-triggered execution
- hỗ trợ review notes và resolution state qua `reconciliation_review_record` collection
- persist reconciliation results theo batch write (`RESULT_WRITE_BATCH_SIZE = 5000`)

### Approval and Mapping Lifecycle

- `src/api/mappings.py`
- `src/api/review_packets.py`
- `src/models/mapping_config.py`
- `src/models/review_packet.py`
- `src/models/copilot_action.py`
- `src/models/post_approval_run.py`
- `src/config/config_health.py`
- `src/services/review_packet_actions.py`
- `src/services/mapping_contract.py`

**Responsibilities:**

- tạo hoặc review mapping proposals
- duy trì approved runtime mappings riêng biệt với pending proposals
- track review packets và Copilot actions
- hỗ trợ bốn luồng quyết định: **Approve-Activate**, **Approve-Keep-Current**, **Reject**, và **Send to Mapping Studio**
- **Approve-Activate flow:** dùng `PostApprovalRun` model để tracking long-running reprocess + reconcile flows
- chạy background task (`asyncio.create_task`) sau approve để thực hiện re-ingestion và re-reconciliation
- dùng `summarize_runtime_error` từ `src/core/error_formatting.py` để UI-safe error summaries
- mapping contract normalization và validation qua `src/services/mapping_contract.py`

### Automation

- `src/scheduler/`
- `src/fetchers/`
- `src/api/automation.py`

**Responsibilities:**

- load enabled fetch configs
- fetch partner files via configured method (SFTP, filedrop, API)
- run ingestion
- expose automation visibility and run-now control
- unified runtime run tracking (`partner_runtime_run` collection) cho scheduler-triggered và manual reconciliation

### AI-Assisted Analysis

- `src/analysis/`
- `src/api/insights.py`
- `src/api/reconciliation.py`
- `src/services/copilot_context.py`

**Responsibilities:**

- summarize reconciliation outcomes
- generate discrepancy views and daily reports
- provide contextual Copilot guidance cho các dashboard screens (intake, review, reconciliation, automation)
- response caching và cache invalidation sau post-approval reprocess

### Services

- `src/services/copilot_context.py` — Rule-based Copilot context for the operations dashboard
- `src/services/mapping_contract.py` — Shared mapping contract normalization, serialization, and validation helpers
- `src/services/review_packet_actions.py` — Shared review packet approval, reprocessing, and post-approval run orchestration
- `src/services/runtime_runs.py` — Helpers for unified runtime run visibility (create/update/serialize `PartnerRuntimeRun`)

### Core Utilities

- `src/core/enums.py` — Core enums: `ProcessingStatus`, `TransactionStatus`, `FileType`, `ReconciliationStatus`, `ReconciliationScopeType`
- `src/core/types.py` — Canonical types: `FieldMapping`, `CanonicalTransaction`, `PartnerData`, `ValidationError`, `ProcessingStats`
- `src/core/constants.py` — System constants: `DEFAULT_CURRENCY`, `FILE_HASH_KEY`, duplicate key patterns
- `src/core/error_formatting.py` — UI-safe error summarization helpers (`summarize_runtime_error`) cho status fields và background task error handling

## Request Surface

API hiện đang đăng ký các router groups sau (xem `src/api/__init__.py`):

| Router module | Prefix | Registered as |
|---|---|---|
| `insights` | `/api/v1` | `insights_router` (insights + reports) |
| `reconciliation` | `/api/v1/reconciliation` | `reconciliation_router` |
| `data_explorer` | `/api/v1/data` | `data_explorer_router` |
| `mappings` | `/api/v1/mappings` | `mappings_router` |
| `mappings` (v2) | `/api/v1/mapping` | `mappings_v2_router` |
| `copilot` | `/api/v1/copilot` | `copilot_router` |
| `operations` | `/api/v1/operations` | `operations_router` |
| `review_packets` | `/api/v1/review-packets` | `review_packets_router` |
| `automation` | `/api/v1/automation` | `automation_router` |
| `audit` | `/api/v1/audit` | `audit_router` |

**Tổng cộng 11 router groups** (insights/reports chung một router).

## Data Stores

MongoDB and PostgreSQL are dual persistence stores. MongoDB handles configs, review packets, audit events, and flexible document storage. PostgreSQL (via `asyncpg` + SQLAlchemy) handles bulk transactional data — ingestion uses `COPY` for high-speed writes, and reconciliation uses SQL joins for in-database matching. Indexes được apply tại startup bởi `src/models/indexes.py` (MongoDB) và `src/models/postgres.py:init_postgres_db` (PostgreSQL).

### Collections

| Collection | Purpose | Key models |
|---|---|---|
| `reconciliation_file` | File metadata, processing status, scope type | `ReconciliationFile` |
| `data_container` | Partner canonical records (ingested rows) | `DataContainer` |
| `internal_transaction` | Internal/backend transaction records | `InternalTransaction` |
| `reconciliation_result` | Reconciliation match/mismatch results | `ReconciliationResult` |
| `reconciliation_mapping_config` | Field mapping configs (approved + pending) | `MappingConfig` |
| `review_packet` | Review packets for approval workflows | `ReviewPacket` |
| `copilot_action` | Copilot action tracking | `CopilotAction` |
| `fetch_config` | Automation fetch configuration | `FetchConfig` |
| `reconciliation_run` | Manual reconciliation run tracking | `ReconciliationRun` |
| `post_approval_run` | Post-approval reprocessing tracking | `PostApprovalRun` |
| `partner_runtime_run` | Unified runtime visibility (scheduler/manual/post-approval) | `PartnerRuntimeRun` |
| `reconciliation_review_record` | Review notes and resolution state per record | `ReconciliationReviewRecord` |

Index definitions chi tiết xem tại `src/models/indexes.py`.

## Frontend Shape

The active dashboard is `frontend-next/`.

Main active views:

- Review Center
- Reconciliation
- Mapping Studio
- Automation

Review Center owns the operator approval workflow:

1. Load pending review packets.
2. Confirm file scope.
3. Review or adjust draft mapping.
4. Run runtime validation.
5. Approve/reject.
6. Track post-approval ingestion and reconciliation progress.

The old `frontend/` directory is legacy/reference only.

## Operational Notes

- Root README là canonical startup doc.
- API-serving behavior nên được document từ `run.py` và `src/api/__init__.py`.
- Approval-driven mapping behavior là first-class runtime concept.
- Background tasks tracking dùng `app.state.background_tasks` (set of `asyncio.Task`).
- Error formatting dùng `summarize_runtime_error` để giữ UI-facing status fields ngắn gọn.

---

*Architecture analysis: 2026-06-16*
