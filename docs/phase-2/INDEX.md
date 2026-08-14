# Phase 2 — Sprint Index

Phase 2 tập trung vào độ tin cậy của fetch/ingestion runtime: idempotency, source-unit checkpoint, recovery, workflow orchestration, data quality và observability. Reconciliation, review và dashboard chỉ được chạm ở các integration contract cần để vận hành các luồng này.

> **Quy ước quan trọng:** Sprint 2.5 là sprint hợp nhất gồm **Airflow integration** và **recovery hardening**. Tài liệu cũ `sprint-2.6-recovery-hardening.md` vẫn giữ tên file để bảo toàn liên kết lịch sử, nhưng không còn được xem là Sprint 2.6 độc lập.

## Sprint 1 — Idempotency và duplicate protection

**Trạng thái:** Đã triển khai, có benchmark/evaluation.

- [Core function index](sprint-1-index.md)
- [Idempotency plan](sprint-1-idempotency.md)
- [Implementation report](sprint-1-idempotency-report.md)
- [Evaluation and benchmark spec](sprint-1-eval-benchmark.md)
- [Benchmark execution run](sprint-1-eval-benchmark-run.md)
- [Summary report](sprint-1-summary.md)
- [MOMO E2E guide](momo-e2e-test-guide.md)

Phạm vi chính: file claim theo hash, fetch-unit identity, ingestion key, conflict-safe batch write và outcome accounting.

## Sprint 2 — Incremental processing và recovery nền tảng

**Trạng thái:** Đã triển khai; tiếp tục được harden trong Sprint 2.5 hợp nhất.

- [Incremental processing and recovery plan](sprint-2-incremental-recovery.md)
- [Evaluation execution run](sprint-2-eval-run.md)
- [Pagination, replay và failure/resume example](ingestion-pagination-example.md)

Phạm vi chính: API pagination, FileDrop/SFTP source units, checkpoint sequencing, retry policy, terminal state, ViettelPay recovery demo và ordered FileDrop backfill.

## Sprint 2.5 — Airflow integration và recovery hardening

**Trạng thái:** Acceptance chưa hoàn tất: 6/11 criteria đã đạt; 5 criteria còn pending. Pilot/automated verification đã có, live production acceptance còn phụ thuộc môi trường.

- [Airflow integration, pilot và migration runbook](sprint-2.5-airflow-migration.md)
- [Recovery hardening evidence — nội dung hợp nhất từ Sprint 2.6](sprint-2.6-recovery-hardening.md)

Các capability của sprint hợp nhất:

- Airflow 3.3 `reconciliation_ingestion` làm control plane duy nhất của Compose pilot.
- API submit/retry/backfill qua Airflow REST gateway; correlation giữ `runtimeRunId`, `dagRunId`, `taskId`, `mapIndex`.
- `AIRFLOW_GLOBAL_SCHEDULE=none` và `AIRFLOW_TASK_RETRIES=0` cho manual pilot.
- Checkpoint/raw staging/review packet/replay vẫn do application sở hữu.
- Recovery timeline, same-DAG-run retry, full-stream review, timezone evidence, ordered backfill và failure classification.

## Sprint 3 — Data quality và quarantine

**Trạng thái:** Kế hoạch mở rộng.

- [Data quality and quarantine plan](sprint-3-data-quality.md)

Phạm vi dự kiến: EDA trước ingestion, quality gates, quarantine contract và operator visibility.

## Sprint 4 — Observability

**Trạng thái:** Kế hoạch mở rộng; runtime visibility nền tảng đã có trong các sprint trước.

- [Observability plan](sprint-4-observability.md)

Phạm vi dự kiến: metrics, structured logs, alerting, dashboard operational signals và acceptance evidence.

## Ma trận sprint

| Sprint | Mục tiêu | Tài liệu chính | Trạng thái |
|---|---|---|---|
| 1 | Idempotency | `sprint-1-index.md`, report, benchmark | Implemented |
| 2 | Incremental/recovery | `sprint-2-incremental-recovery.md` | Implemented |
| 2.5 | Airflow + recovery hardening | `sprint-2.5-airflow-migration.md` + hardening evidence | Partial acceptance: 5 criteria pending |
| 3 | Data quality/quarantine | `sprint-3-data-quality.md` | Planned |
| 4 | Observability | `sprint-4-observability.md` | Planned |
