# Project Milestones

**Cập nhật:** 2026-08-28

## Milestone 1 — Foundation

**Trạng thái:** Baseline đã triển khai.

Đã có file ingestion, dynamic mapping, normalization, validation, persistence, deterministic reconciliation, review/audit foundation và dashboard vận hành. Boundary hiện tại được mô tả tại [Architecture](phase-1/ARCHITECTURE.md).

## Milestone 2 — Phase 2: Ingestion reliability

**Trạng thái:** Sprint 1 và 2 đã triển khai; Sprint 2.5 đang ở trạng thái partial acceptance với 5 criteria còn pending; Sprint 3 đã hoàn tất ở phạm vi local mock-data với quyết định `GO (demo-only)`; Sprint 4 đã chốt observability trên Schedules với quyết định `closed — no candidate promoted`.

| Sprint | Phạm vi | Trạng thái evidence |
|---|---|---|
| 1 | Idempotency, duplicate protection, benchmark | Implemented + benchmark |
| 2 | Incremental processing, checkpoint, recovery, backfill | Implemented + regression/demo |
| 2.5 | Airflow integration + recovery hardening (gộp nội dung cũ của 2.6) | Partial acceptance: 6/11 đạt, 5 pending; local health verified, live business evidence còn phụ thuộc môi trường |
| 3 | Data quality và quarantine | Implemented; local mock-data acceptance `GO (demo-only)` |
| 4 | Observability | `closed — no candidate promoted`; Schedules UI và telemetry hardening đã chốt |

Đọc [Phase 2 Sprint Index](phase-2/INDEX.md) để xem toàn bộ plan, report, evaluation run và runbook của từng sprint.

### Ranh giới Phase 2

Phase 2 ưu tiên fetchers, source units, checkpoint, ingestion pipeline, workflow orchestration, runtime/recovery và các integration contract với review/reconciliation/frontend. Đây không phải là rewrite toàn bộ reconciliation, dashboard hay AI analysis.

## Cách đọc trạng thái

- **Implemented:** code và regression/evaluation tương ứng đã có.
- **Pilot:** đã chạy local/Docker theo runbook.
- **Automated verification:** test code đã pass; live service evidence có thể vẫn cần thu thập.
- **Planned:** tài liệu thiết kế/plan đã có, chưa coi là acceptance hoàn tất.
