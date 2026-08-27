# Documentation Index

README là điểm bắt đầu. Các trang dưới đây mô tả runtime hiện tại; report/evaluation trong `docs/phase-2/` là evidence chi tiết, không phải source thay thế cho index này.

## Runtime hiện tại

- [Architecture](phase-1/ARCHITECTURE.md) — boundary, flow, persistence và API/UI surface.
- [Data flow](phase-1/DATA_FLOW.md) — ingestion, recovery, reconciliation và approval.
- [Module map](phase-1/MODULES.md) — package/symbol map theo codegraph.
- [Development](phase-1/DEVELOPMENT.md) — local setup, command và test.
- [Configuration](phase-1/CONFIGURATION.md) — environment variables.
- [Docker services](../docker/README.md) — Compose services/ports.
- [CI map](CI-MAP.md) — workflow và blast radius.

## Trạng thái và evidence

- [Milestones](MILESTONES.md) — trạng thái foundation và Phase 2.
- [Known issues](KNOWN_ISSUES.md) — pilot constraints và follow-up.
- [Phase 2 index](phase-2/INDEX.md) — plan, report và acceptance theo sprint.
- [Sprint 3 index](phase-2/sprint-3-index.md) — data quality/quarantine.

## Quy tắc cập nhật

Sau thay đổi code, đối chiếu tối thiểu:

1. `codegraph status` và `codegraph sync .` cho file/symbol/dependency.
2. `src/config/settings.py`, `src/analysis/config.py`, `.env.example` cho config.
3. `src/api/`, `frontend-next/src/app/` cho API và UI routes.
4. `docker-compose.yml`, Dockerfiles và `.github/workflows/` cho runtime/CI.

Không thêm kiến trúc hoặc entrypoint vào docs nếu chưa có code và test tương ứng.
