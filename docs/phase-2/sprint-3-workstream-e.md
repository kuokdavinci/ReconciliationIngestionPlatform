# Sprint 3 — Workstream E: Operator quarantine flow

**Trạng thái:** `Implemented` ở operator contract, application, persistence,
API và contract tests.

## Vấn đề và phạm vi

Đảm bảo operator xử lý quarantine record đúng owner, đúng trạng thái, có
idempotency và có audit bounded.

## State/action matrix

| Action | State vào | State ra | Điều kiện |
|---|---|---|---|
| `CLAIM` | `PENDING` | `REPROCESSING` | Atomic lease; một winner |
| `REPROCESS` | `REPROCESSING` | `RESOLVED`/`PENDING` | Current claimant |
| `ACCEPT_EXISTING` | `REPROCESSING` | `RESOLVED` | Verify fingerprint nội bộ; current claimant |
| `REJECT` | `REPROCESSING` | `REJECTED` | Bắt buộc reason không rỗng |
| `ESCALATE` | `PENDING`/`REPROCESSING` | Không đổi | Với `REPROCESSING`, cần current claimant |

Mọi mutation cần `actionId` tối đa 128 ký tự và `expectedStatus`. Idempotency
scope là `(recordId, actionId)`. Replay cùng action trả bounded result cũ và
không tạo transition/audit lần hai. Dùng lại `actionId` cho actor/action khác
trả `ACTION_ID_REUSE_CONFLICT`.

## API contract

| Method | Endpoint | Chức năng |
|---|---|---|
| `GET` | `/api/v1/quarantine` | Queue có filter, cursor và summary |
| `GET` | `/api/v1/quarantine/{record_id}` | Chi tiết record đã redact |
| `POST` | `/api/v1/quarantine/{record_id}/claim` | Claim lease |
| `POST` | `/api/v1/quarantine/{record_id}/reprocess` | Replay source hoặc corrected row |
| `POST` | `/api/v1/quarantine/{record_id}/accept-existing` | Chấp nhận existing sau fingerprint check |
| `POST` | `/api/v1/quarantine/{record_id}/reject` | Discard có reason |
| `POST` | `/api/v1/quarantine/{record_id}/escalate` | Tăng escalation level |
| `POST` | `/api/v1/quarantine/source-units/{source_unit_key}/resume` | Resume source unit |

Actor lấy từ `operatorId` hoặc `X-Actor`. `REJECT` và `ESCALATE` cần reason tối
đa 500 ký tự. Response chỉ trả record/action ID, outcome, state, owner,
priority, due time, escalation, counters và stable error codes.

| HTTP | Dùng cho |
|---:|---|
| `400` | Actor/payload contract sai |
| `404` | Không có record |
| `409` | Stale status, sai owner, fingerprint hoặc action conflict |
| `422` | Thiếu reason/corrected row/source evidence hoặc validation outcome |
| `503` | Dependency retryable |

## Queue, SLA và escalation

| Hạng mục | Contract |
|---|---|
| SLA mặc định | 24 giờ; cấu hình bằng `APP_INGESTION_QUARANTINE_REVIEW_SLA_HOURS` |
| `HIGH` priority | `CONFLICTING_DUPLICATE` và `FATAL` |
| `NORMAL` priority | Các record còn lại |
| Overdue | `PENDING`/`REPROCESSING` và `now >= reviewDueAt` |
| Escalation | Tăng tối đa level `3`; giữ nguyên state và owner |
| Expired claim | Trả về `PENDING` trước claim mới |
| Queue summary | Độc lập page/cursor; gồm pending, reprocessing, resolved, rejected, overdue, highPriority |

Escalation không gửi notification, chuyển owner hoặc enforce RBAC trong Sprint
3.

## Audit và redaction

| Hạng mục | Quy tắc |
|---|---|
| Audit event | `INGESTION_QUARANTINE`, actor/action, state cũ/mới, outcome, bounded reason và correlation |
| Audit idempotency | Unique action-scoped index trên `(entityType, entityId, metadata.actionId)` |
| Source-unit resume | Audit `INGESTION_QUARANTINE_SOURCE_UNIT`, `HELD → RESUMED`; ngoài row action ledger |
| Không được lộ | Raw row, credential, full exception, parsed timestamp, incoming/existing fingerprint |
| Detail/history | Chỉ sanitized evidence và bounded resolution history |

## Evidence

| Contract | Evidence |
|---|---|
| Claim race | Atomic `find_one_and_update`, một winner |
| Owner/CAS | Stale status và wrong owner bị chặn |
| Reprocess | Source-backed replay dùng shared row processor |
| Accept/reject | Fingerprint verify nội bộ; reject cần reason |
| Escalation | Owner CAS, giữ state, cap 3 |
| Replay/audit | Không gọi persistence hoặc ghi audit lần hai |
| Queue | Filter, cursor, summary, priority và overdue tests |
