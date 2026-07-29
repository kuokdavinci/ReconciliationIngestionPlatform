# Documentation Index

Tài liệu dự án được chia theo milestone/phase. Numbering của plan bắt đầu từ `1` trong từng phase.

## Phase 1 — Foundation và hệ thống hiện tại

- [Plan 1 — Foundation](phase-1/PLAN-01-FOUNDATION.md)
- [Architecture](phase-1/ARCHITECTURE.md)
- [Configuration](phase-1/CONFIGURATION.md)
- [Data Flow](phase-1/DATA_FLOW.md)
- [Development Guide](phase-1/DEVELOPMENT.md)
- [Module Map](phase-1/MODULES.md)
- [Ingest/Reconciliation Trace](phase-1/INGEST_RECON_TRACE.md)
- [Performance Trace](phase-1/performance/INGEST_RECON_TRACE.md)

## Phase 2 — Ingestion reliability

Milestone mới: hoàn thiện độ tin cậy của fetch/ingestion pipeline. Phase này không bao gồm reconciliation logic, frontend hoặc AI.

- [Plan 1 — Idempotency](phase-2/PLAN-01-IDEMPOTENCY.md)
- [Plan 2 — Incremental Processing & Recovery](phase-2/PLAN-02-INCREMENTAL-RECOVERY.md)
- [Plan 3 — Data Quality & Quarantine](phase-2/PLAN-03-DATA-QUALITY.md)
- [Plan 4 — Observability](phase-2/PLAN-04-OBSERVABILITY.md)
- [Known Issues](KNOWN_ISSUES.md)

## Scope boundary

Các tài liệu Phase 2 chỉ đề xuất thay đổi ở fetchers, scheduler, ingestion pipeline, validation, persistence, models và runtime observability. `src/reconciliation/`, `frontend-next/` và `src/analysis/` không thuộc milestone này.
