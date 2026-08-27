# Phase 2 — Chỉ mục Sprint

Phase 2 tập trung vào độ tin cậy của fetch/ingestion runtime: idempotency, source-unit checkpoint, recovery, workflow orchestration, data quality và observability. Reconciliation, review và dashboard chỉ được chạm ở các integration contract cần để vận hành các luồng này.

> **Quy ước quan trọng:** Sprint 2.5 là sprint hợp nhất gồm **Airflow integration** và **recovery hardening**. Sprint 2.6 không còn là sprint độc lập; nội dung đã được đưa vào tài liệu Sprint 2.5.

## Sprint 1 — Idempotency và duplicate protection

**Trạng thái:** Đã triển khai, có benchmark/evaluation.

- [Chỉ mục hàm core](sprint-1-index.md)
- [Kế hoạch idempotency](sprint-1-idempotency.md)
- [Đặc tả evaluation và benchmark](sprint-1-eval-benchmark.md)
- [Benchmark execution run](sprint-1-eval-benchmark-run.md)
- [Hướng dẫn MOMO E2E](momo-e2e-test-guide.md)

Phạm vi chính: file claim theo hash, fetch-unit identity, ingestion key, conflict-safe batch write và outcome accounting.

## Sprint 2 — Incremental processing và recovery nền tảng

**Trạng thái:** Đã triển khai; tiếp tục được harden trong Sprint 2.5 hợp nhất.

- [Kế hoạch incremental processing và recovery](sprint-2-incremental-recovery.md)
- [Chỉ mục hàm core — Sprint 2 và Sprint 2.5](sprint-2-index.md)
- [Biên bản chạy evaluation](sprint-2-eval-run.md)
- [Ví dụ pagination, replay và failure/resume](ingestion-pagination-example.md)

Phạm vi chính: API pagination, FileDrop/SFTP source units, checkpoint sequencing, retry policy, terminal state, ViettelPay recovery demo và ordered FileDrop backfill.

## Sprint 2.5 — Airflow integration và recovery hardening

**Trạng thái:** Acceptance chưa hoàn tất: 6/11 criteria đã đạt; 5 criteria còn pending. Pilot/automated verification và local Compose service health đã có; live business-flow/production acceptance còn phụ thuộc môi trường.

- [Airflow integration, pilot và runbook migration](sprint-2.5-airflow-migration.md)
- [Chỉ mục hàm core — Sprint 2 và Sprint 2.5](sprint-2-index.md)

Các capability của sprint hợp nhất:

- Airflow 3.3 `reconciliation_ingestion` làm control plane duy nhất của Compose pilot.
- API submit/retry/backfill qua Airflow REST gateway; correlation giữ `runtimeRunId`, `dagRunId`, `taskId`, `mapIndex`.
- `AIRFLOW_GLOBAL_SCHEDULE=none` và `AIRFLOW_TASK_RETRIES=0` cho manual pilot.
- Checkpoint/raw staging/review packet/replay vẫn do application sở hữu.
- Recovery timeline, same-DAG-run retry, full-stream review, timezone evidence, ordered backfill và failure classification.

## Sprint 3 — Data quality và quarantine

**Trạng thái:** Workstream A đã hoàn tất riêng phần EDA/profile, provenance,
frozen ingestion baseline, controlled mutation và coverage handoff cho Fraud
Detection Dataset. Workstream B đã triển khai quality contract/gate,
duplicate classification, conflict quarantine và bounded source-unit outcome;
Workstream C đã triển khai normalization/validation contract và có full-dataset
v2 evidence. Workstream D đã triển khai quarantine
lifecycle, operator resolution contract, production row/fingerprint wiring,
audit/counters, API và source-unit resume; production approval và Workstream
E–F vẫn còn pending.

- [Chỉ mục Sprint 3 — Data Quality và Quarantine](sprint-3-index.md)
- [Kế hoạch data quality và quarantine](sprint-3-data-quality.md)
- [Sprint 3 index](sprint-3-index.md)
- [Workstream B — quality contract và Airflow-ready outcome](sprint-3-workstream-b-quality-contract.md)
- [Workstream C — normalization và validation contract](sprint-3-workstream-c-normalization-validation.md)
- [Workstream C — full-dataset v2 baseline](sprint-3-workstream-c-baseline.md)
- [Review EDA và rule candidates](sprint-3-eda-review.md)
- [Workstream A decision matrix](sprint-3-workstream-summary.md)

Phạm vi còn lại: operator approval flow, production observability, partner
sign-off và production acceptance. Notebook EDA vẫn không thay đổi và chỉ
chạy trên Kaggle.

## Sprint 4 — Observability

**Trạng thái:** Kế hoạch mở rộng; runtime visibility nền tảng đã có trong các sprint trước.

- [Kế hoạch observability](sprint-4-observability.md)

Phạm vi dự kiến: metrics, structured logs, alerting, dashboard operational signals và acceptance evidence.

## Ma trận sprint

| Sprint | Mục tiêu | Tài liệu chính | Trạng thái |
|---|---|---|---|
| 1 | Idempotency | `sprint-1-index.md`, benchmark | Đã triển khai |
| 2 | Incremental/recovery | `sprint-2-index.md`, `sprint-2-incremental-recovery.md` | Đã triển khai |
| 2.5 | Airflow + recovery hardening | `sprint-2-index.md`, `sprint-2.5-airflow-migration.md` | Còn 5 tiêu chí acceptance |
| 3 | Data quality/quarantine | `sprint-3-index.md`, Workstream B/C/D evidence | A/B/C/D implemented; E–F pending |
| 4 | Observability | `sprint-4-observability.md` | Kế hoạch |
