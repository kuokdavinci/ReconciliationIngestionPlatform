# Phase 2 — Index Sprint

| Sprint | Mục tiêu | Tài liệu chính | Trạng thái |
|---|---|---|---|
| 1 | Idempotency và duplicate protection | [Sprint 1 index](sprint-1-index.md), [idempotency](sprint-1-idempotency.md), benchmark/evaluation | Đã triển khai |
| 2 | Incremental processing và recovery | [Sprint 2 index](sprint-2-index.md), [incremental/recovery](sprint-2-incremental-recovery.md) | Đã triển khai |
| 2.5 | Airflow integration và recovery hardening | [Migration](sprint-2.5-airflow-migration.md), [Sprint 2 index](sprint-2-index.md) | Còn 5 tiêu chí acceptance |
| 3 | Data quality và quarantine | [Sprint 3 index](sprint-3-index.md) | A–E đã triển khai; F `GO (demo-only)` |
| 4 | Observability | [Sprint 4 index](sprint-4-index.md), [observability](sprint-4-observability.md) | `closed — no candidate promoted` |

## Sprint 3

Sprint 3 dùng một file chính cho mỗi Workstream. [Sprint 3 index](sprint-3-index.md)
liệt kê chức năng, vấn đề giải quyết và file tương ứng.

Sprint 2.5 là sprint hợp nhất của Airflow integration và recovery hardening;
không có Sprint 2.6 độc lập.

## Sprint 4

Sprint 4 dùng một index ngắn cho tài liệu observability và các report benchmark.
[Sprint 4 index](sprint-4-index.md) là điểm vào chính; tài liệu observability
ghi contract và acceptance, còn benchmark reports giữ evidence của baseline và
quyết định không promote candidate.
