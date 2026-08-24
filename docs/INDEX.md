# Documentation Index

Index canonical của tài liệu dự án. README là điểm bắt đầu; tài liệu chi tiết được tổ chức theo phase và milestone.

## Bắt đầu nhanh

- [README](../README.md) — cài đặt, chạy local, Airflow pilot, dashboard và test.
- [Architecture hiện tại](phase-1/ARCHITECTURE.md) — boundary, data flow, API surface và persistence.
- [Module map](phase-1/MODULES.md) — trách nhiệm của các package chính.
- [Configuration](phase-1/CONFIGURATION.md) — biến môi trường và nguồn cấu hình.
- [Docker services](../docker/README.md) — service, volume và port của Compose.
- [CI map](CI-MAP.md) — workflow, command và blast radius.

## Phase 1 — Foundation

- [Foundation plan](phase-1/PLAN-01-FOUNDATION.md)
- [Architecture](phase-1/ARCHITECTURE.md)
- [Configuration](phase-1/CONFIGURATION.md)
- [Data flow](phase-1/DATA_FLOW.md)
- [Development guide](phase-1/DEVELOPMENT.md)
- [Module map](phase-1/MODULES.md)
- [Ingest/reconciliation trace](phase-1/INGEST_RECON_TRACE.md)
- [Performance trace](phase-1/performance/INGEST_RECON_TRACE.md)

## Phase 2 — Ingestion reliability

Index đầy đủ theo sprint nằm tại [docs/phase-2/INDEX.md](phase-2/INDEX.md). Phase 2 mở rộng từ idempotency sang incremental recovery, Airflow control plane, recovery hardening, data quality và observability.

### Sprint 3 — Data quality và quarantine

- [Kế hoạch và trạng thái Sprint 3](phase-2/sprint-3-data-quality.md)
- [Workstream C — normalization và validation evidence](phase-2/sprint-3-workstream-c-normalization-validation.md) — `implemented; full-dataset v2 evidence pending`

## Vận hành và giới hạn

- [Milestones](MILESTONES.md) — trạng thái milestone và acceptance evidence.
- [Known issues](KNOWN_ISSUES.md) — giới hạn môi trường, pilot và follow-up.
- [CI map](CI-MAP.md) — nhóm test theo thay đổi.

## Quy ước cập nhật

Khi code thay đổi, đối chiếu tối thiểu các nguồn sau trước khi sửa docs:

1. `.codegraph/codegraph.db` và `codegraph status` cho file/symbol/dependency.
2. `src/config/settings.py` và `.env.example` cho cấu hình.
3. `src/api/` và `frontend-next/src/app/` cho request/UI surface.
4. `docker-compose.yml`, `Dockerfile.*` và `.github/workflows/` cho runtime/CI.

Các report, evaluation run và runbook trong `docs/phase-2/` là evidence chi tiết; không thay thế index canonical.
