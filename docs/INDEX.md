# Index tài liệu

`README.md` là điểm bắt đầu. Index này liệt kê tài liệu runtime và các index
theo Phase/Sprint.

## Runtime hiện tại

| Tài liệu | Chức năng | Giải quyết vấn đề |
|---|---|---|
| [Architecture](phase-1/ARCHITECTURE.md) | Boundary, flow, persistence, API/UI | Xác định cấu trúc runtime và điểm tích hợp |
| [Data flow](phase-1/DATA_FLOW.md) | Ingestion, recovery, reconciliation, approval | Theo dõi dữ liệu qua các bước xử lý |
| [Module map](phase-1/MODULES.md) | Package/symbol map theo codegraph | Tìm module và dependency liên quan |
| [Development](phase-1/DEVELOPMENT.md) | Local setup, command, test | Chạy và kiểm tra hệ thống local |
| [Configuration](phase-1/CONFIGURATION.md) | Environment variables | Xác định cấu hình runtime |
| [Docker services](../docker/README.md) | Compose services và ports | Khởi động đúng các service |
| [CI map](CI-MAP.md) | Workflow và blast radius | Biết test nào kiểm tra từng thay đổi |
| [Ingest/reconciliation trace](phase-1/INGEST_RECON_TRACE.md) | Trace và benchmark theo flow | Kiểm tra đường đi và thời gian xử lý |
| [Performance trace](phase-1/performance/INGEST_RECON_TRACE.md) | Số liệu ingestion/reconciliation | Theo dõi hiệu năng runtime |

## Trạng thái và Sprint

| Tài liệu | Chức năng | Giải quyết vấn đề |
|---|---|---|
| [Milestones](MILESTONES.md) | Trạng thái foundation và Phase 2 | Biết phần nào đã hoàn thành |
| [Known issues](KNOWN_ISSUES.md) | Pilot constraints và follow-up | Theo dõi giới hạn và việc còn lại |
| [Phase 2 index](phase-2/INDEX.md) | Danh sách tài liệu theo Sprint | Tìm nhanh tài liệu của từng Sprint |
| [Sprint 3 index](phase-2/sprint-3-index.md) | Danh sách file, Workstream và phạm vi | Tìm đúng tài liệu cho data quality/quarantine |
| [Sprint 4 index](phase-2/sprint-4-index.md) | Observability trên Schedules và benchmark decision | Tìm contract và evidence của Sprint 4 |

Các report/evaluation trong `docs/phase-2/` là evidence chi tiết. Khi cần xác
định behavior hiện tại, ưu tiên runtime code, test và các tài liệu trong mục
Runtime hiện tại.
