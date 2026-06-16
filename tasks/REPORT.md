# Báo Cáo Toàn Bộ Thay Đổi — `pr/reconciliation-engine-scaling`

**Ngày:** 2026-06-16  
**Base:** `main` → **Head:** `pr/reconciliation-engine-scaling`  
**Tổng quan:** 50 files changed, 8,778 insertions(+), 1,670 deletions(-)

---

## 1. Tái Cấu Trúc Source Code

### Services Layer mới (`src/services/`)

- **`src/services/mapping_contract.py`** (98 lines) — `canonicalize_field_mappings()`, `serialize_field_mappings()`, `validate_mapping_contract()`: chuẩn hóa field mappings từ AI proposal trước khi lưu, validation độc lập.
- **`src/services/review_packet_actions.py`** (432 lines) — Logic approve/reject/keep-current/approve-activate cho review packet được tách riêng. Bundle approval + reprocess + reconcile workflow.
- **`src/services/runtime_runs.py`** (79 lines) — `serialize_partner_runtime_run()` helper cho automation dashboard.

### Models mới (`src/models/`)

- **`src/models/reconciliation_run.py`** (59 lines) — `ReconciliationRun`: theo dõi mỗi lần chạy reconcile (partner, date, status, stats, startedAt/completedAt).
- **`src/models/post_approval_run.py`** (73 lines) — `PostApprovalRun`: tracking sau khi review packet approve-activate (source_file_id, runs, approved_config_id, overall_status).
- **`src/models/partner_runtime_run.py`** (81 lines) — `PartnerRuntimeRun`: QUEUED → FETCHING → INGESTING → WAITING_RECONCILE → RECONCILING → COMPLETED/FAILED lifecycle.

### Core mới

- **`src/core/error_formatting.py`** (35 lines) — `summarize_runtime_error()`: chuyển exception stack trace thành structured error dict cho API response.

### Indexes mở rộng

- **`src/models/indexes.py`** (+39 lines) — Thêm indexes cho `reconciliation_run`, `post_approval_run`, `partner_runtime_run`.

### Normalizer cải tiến

- **`src/normalizer/normalizer.py`** (+81 lines) — Extra field support, improved error collection patterns.

---

## 2. Reconciliation Engine Refactor

**File:** `src/reconciliation/engine.py` (435 lines changed, +231/-135)

- **Streaming mode:** Engine xử lý theo batch thay vì load full dataset vào memory.
- **Scope resolution tách riêng:** `_get_scoped_partner_keys()` được refactor thành function riêng, hỗ trợ REPLACEMENT/INCREMENTAL/FULL_SNAPSHOT.
- **Reconciliation Run tracking:** Mỗi lần reconcile tạo `ReconciliationRun` record, track startedAt/completedAt/stats.
- **Batch classify:** `classify_batch()` xử lý status classification và amount comparison trong batch.
- **Idempotent persist:** delete-many + insert-many pattern cho reconciliation results.

---

## 3. Cải Tiến AI Analysis Layer

**Files:** `src/analysis/insights.py` (+212/-21), `prompts.py` (+19), `schemas.py` (+13), `services.py` (+10/-1)

- **Aggregated metrics query:** `_query_summary_metrics()` — MongoDB aggregation pipeline thay vì load full dataset + compute trong Python. Query 5 grouped statuses thay vì 100k rows.
- **Selected error sampling:** `_query_selected_error_results()` — bounded sampling (50 records/status) cho discrepancy insight. Thay vì quét full dataset.
- **`SelectedErrorSignal` model** — Summarized signal từ bounded sample records.
- **`_compute_summary_hash()`** — Cache key dùng hash của summary aggregation thay vì hash full dataset.
- **Prompt section mới:** `_format_selected_error_signals_section()` — bounded signals được format vào LLM prompt.

### Benchmark kết quả (từ `tasks/eval.md`)

| Metric | 100k Baseline | 100k Optimized | 1M Baseline | 1M Optimized |
|--------|:---:|:---:|:---:|:---:|
| Results page 1 | 1.0412s | **0.0545s** | 11.4394s | **0.4792s** |
| Summary insight prep | 3.1334s | **0.2709s** | 35.1928s | **2.3620s** |
| Discrepancy prep | ~3.03s | **~0.27s** | ~33.99s | **~2.49s** |
| Reconcile engine full | 6.9447s | 8.1372s | 153.270s | **97.893s** |

Cải thiện query + insight prep: **11.7x** (100k), **15.1x** (1M).  
Engine cải thiện: **1.57x** (1M dataset).

---

## 4. Review Packet & API Refactor

**File:** `src/api/review_packets.py` (652 lines changed, +280/-208)

- **`PostApprovalRun` tracking:** Sau approve-activate, tạo `PostApprovalRun` record tracking toàn bộ reprocess + reconcile lifecycle.
- **Background task pattern:** `asyncio.create_task()` + `_track_background_task()` cho reprocess + reconcile.
- **`summarize_runtime_error()`:** Structured error response thay vì generic 500.
- **`_run_runtime_validation`:** Cải thiện validation logic, sample rows được xử lý qua MappingContract service.

**File:** `src/api/automation.py` (+101/-14)

- **Partner runtime visibility:** `list_automation_jobs()` trả về `latestRuntimeRun`, `activeRuntimeRun`, `hasPendingFile`, `status`/`statusMessage`.
- **Background run-now:** `run_automation_job_now()` dùng `asyncio.create_task()` + tracking, trả về ngay `{"queued": true}`.
- **PartnerRuntimeRun lifecycle:** Mỗi lần chạy fetch tạo PartnerRuntimeRun record, cập nhật status qua từng stage.

**File:** `src/api/mappings.py` (+103/-14)

- **`MappingContractService`:** `canonicalize_field_mappings()` + `validate_mapping_contract()` trong `_create_mapping_proposal_from_source_file`.
- **`approve_mapping_config_action()` / `reject_mapping_config_action()`:** Logic action tách riêng, router wrapper giữ API contract.
- **`allocate_next_version()`:** Delegate version allocation vào repository thay vì inline count_documents.

**File:** `src/api/copilot.py` (+13/-9)

- **Action function rename:** `approve_activate_packet` → `approve_activate_packet_action`, `reject_packet` → `reject_packet_action`, v.v. — phân biệt rõ giữa internal action handler và public route handler.

**File:** `src/api/reconciliation.py` (+125/-87)

- **Server-side pagination:** `find_page_by_partner_and_date()` dùng `.skip().limit()` thay vì in-memory slice.
- **Review records endpoints:** `get_review_records()`, `list_review_records()`.
- **Re-run reconciliation:** `rerun_reconciliation()` endpoint.
- **Decimal128 comparison:** amount range filter dùng MongoDB query thay vì Python-side filter.

---

## 5. Frontend & Vite Build

- **Vite integration:** `frontend/vite.config.js` (+26), `frontend/package.json` (+14), `frontend/package-lock.json` (+1026).
- **Dashboard UI refactor:** `frontend/app.js` (2,815 lines changed) — Review Center flow đơn giản hóa, runtime visibility.
- **Styles:** `frontend/styles.css` (1,121 lines changed) — Dark theme tối ưu, review packet styling.
- **Server proxy:** `frontend/server.py` (+4) — CORS/config tweaks.

---

## 6. Docs & Tasks

- **`docs/` updated (5 files, +542/-139):** ARCHITECTURE.md, CONFIGURATION.md, DATA_FLOW.md, DEVELOPMENT.md, MODULES.md — đồng bộ với codebase hiện tại.
- **`tasks/REPORT.md`** — File này (báo cáo tổng hợp).
- **`tasks/eval.md`** (+120) — Benchmark A/B baseline vs optimized với dataset 100k và 1M.
- **`reconciliation-flow-benchmark.md`** (+68) — Hướng dẫn benchmark flow.
- **`refine-reconciliation-performance.md`** (+527) — Phân tích chi tiết performance optimization.
- **`scripts/benchmark_reconcile_million.py`** (+687) — Benchmark script cho dataset 1M rows.

---

## 7. Tests

**Files cập nhật:**
- `tests/test_api_review_packets.py` (+181/-30) — Review packet approve-activate flow, PostApprovalRun tracking.
- `tests/test_api_reconciliation.py` (+31/-8) — Pagination, review records endpoints.
- `tests/test_reconciliation.py` (+47/-5) — Engine streaming, scope resolution.

---

## Tổng Kết

| Hạng mục | Chi tiết |
|----------|----------|
| **Files changed** | 50 |
| **Insertions** | 8,778 |
| **Deletions** | 1,670 |
| **New services** | `mapping_contract.py`, `review_packet_actions.py`, `runtime_runs.py` |
| **New models** | `reconciliation_run`, `post_approval_run`, `partner_runtime_run` |
| **Core addition** | `error_formatting.py` |
| **API refactors** | review_packets (652 chg), automation (101 chg), mappings (103 chg), reconciliation (125 chg) |
| **Engine refactor** | streaming + scope + run tracking (435 chg) |
| **Insight optimization** | aggregation pipeline, bounded sampling (233 chg) |
| **Docs synced** | 5 files in `docs/`, + `tasks/REPORT.md`, `tasks/eval.md` |
| **Benchmark script** | `benchmark_reconcile_million.py` (687 lines) |
