# Sprint 3 — Index Workstream

Sprint 3 xử lý data quality, duplicate classification, quarantine và operator
resolution. Bảng dưới đây là mục lục; chi tiết chỉ nằm trong file tương ứng.

| File | Workstream | Chức năng | Giải quyết vấn đề |
|---|---|---|---|
| [sprint-3-workstream-a.md](sprint-3-workstream-a.md) | A | EDA, profile, provenance và frozen baseline | Có evidence để quyết định rule trước runtime |
| [sprint-3-workstream-b.md](sprint-3-workstream-b.md) | B | Rule registry, file/row gate, duplicate fingerprint, runtime outcome | Quality decision deterministic và bounded |
| [sprint-3-workstream-c.md](sprint-3-workstream-c.md) | C | Timestamp normalization, validation và full-dataset v2 evidence | `timestamp` được đưa về `transDate` nhất quán |
| [sprint-3-workstream-d.md](sprint-3-workstream-d.md) | D | Quarantine lifecycle và source-unit recovery | Xử lý row lỗi/conflict và resume không mất dữ liệu |
| [sprint-3-workstream-e.md](sprint-3-workstream-e.md) | E | Claim, resolve, reject, escalate và audit | Tránh sai owner, xử lý đồng thời và replay action |
| [sprint-3-workstream-f.md](sprint-3-workstream-f.md) | F | Demo acceptance và handoff | Xác nhận contract B–E trong local mock-data |
| [sprint-3-reconciliation-key-evidence.md](sprint-3-reconciliation-key-evidence.md) | Ngoài Workstream | Canonical reconciliation key và audit bounded | Tránh match sai hoặc duplicate key trước migration |

## Trạng thái

| Workstream | Trạng thái |
|---|---|
| A | Đã hoàn tất EDA, provenance, baseline và decision matrix |
| B | `Implemented` |
| C | `Implemented`; đã có full-dataset v2 evidence |
| D | `Implemented` ở contract/application/runtime boundary |
| E | `Implemented` ở operator contract/application boundary |
| F | `GO (demo-only)` |

## Ranh giới Sprint 3

Amount outlier, fraud semantics, entity/location consistency, coordinates,
temporal volume và timestamp precision không phải automatic rejection rule.
Notifications, dashboard, alerting và stage observability thuộc Sprint 4.
