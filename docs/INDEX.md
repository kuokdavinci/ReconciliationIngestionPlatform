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

- [Sprint 1 Summary](phase-2/sprint-1-summary.md)
- [Sprint 1 Index — Core Logic & Architecture Review](phase-2/sprint-1-index.md)
- [Sprint 1 — Idempotency](phase-2/sprint-1-idempotency.md)
- [Sprint 1 — Implementation Report](phase-2/sprint-1-idempotency-report.md)
- [Sprint 1 — Eval & Benchmark Suite](phase-2/sprint-1-eval-benchmark.md)
- [Sprint 1 — Benchmark Execution Run](phase-2/sprint-1-eval-benchmark-run.md)
- [MOMO E2E Test Guide](phase-2/momo-e2e-test-guide.md)
- [Sprint 2 — Incremental Processing & Recovery](phase-2/sprint-2-incremental-recovery.md)
- [Sprint 2 — Evaluation Execution Run](phase-2/sprint-2-eval-run.md)
- [Sprint 2.5 — Airflow Pilot & Migration Runbook](phase-2/sprint-2.5-airflow-migration.md)
- [Sprint 2 / 2.5 — Recovery Hardening Progress](phase-2/sprint-2.6-recovery-hardening.md)
- [Pagination, Replay & Failure/Resume Example](phase-2/ingestion-pagination-example.md)
- [Sprint 3 — Data Quality & Quarantine](phase-2/sprint-3-data-quality.md)
- [Sprint 4 — Observability](phase-2/sprint-4-observability.md)
- [Known Issues](KNOWN_ISSUES.md)

## Scope boundary

Phase 2 tập trung vào fetchers, scheduler/orchestration, ingestion pipeline,
validation, persistence và runtime observability. Sprint 2/2.5 cũng ghi nhận
các integration contract cần thiết với reconciliation và frontend review/recovery;
đây không phải là một rewrite của `src/reconciliation/`, `frontend-next/` hay
`src/analysis/`.
