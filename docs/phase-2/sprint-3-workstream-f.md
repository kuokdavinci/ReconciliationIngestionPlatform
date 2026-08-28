# Sprint 3 — Workstream F: Demo acceptance và handoff

**Trạng thái:** `GO (demo-only)`.

## Vấn đề và phạm vi

Xác nhận các contract B–E chạy đúng trong local Compose với mock-data và ghi
bounded evidence cho Sprint 4. F không thêm runtime behavior.

| F xác nhận | F không triển khai |
|---|---|
| Quality outcome/counter, normalization, quarantine/recovery, operator action, runtime topology | Metrics, structured logs, notifications, dashboard, alerting, stage observability và observability benchmark |

## Gate và kết quả

| Gate | Evidence cần có | Kết quả |
|---|---|---|
| B quality accounting | Counters input/persisted/rejected/duplicate/quarantine reconcile | Pass |
| C normalization/validation | Parity tests và full-dataset v2 artifact | Pass |
| D quarantine/recovery | Replay, conflict hold, checkpoint-safe resume, không duplicate persistence | Contract pass |
| E operator flow | Claim, owner/CAS, actions, escalation, replay, audit, redaction | Contract pass |
| Runtime topology | Compose, API, source, MongoDB, PostgreSQL; Airflow khi chạy full topology | Local Compose pass |

## Execution record

| Kiểm tra | Kết quả |
|---|---|
| Full local pytest | `1326 passed, 18 skipped` trong `19.26s` |
| Focused B/C/D/E/API gate | `209 passed` trong `2.68s` |
| Ruff | Pass |
| Mypy | Pass, `207 source files` |
| Compose config | Pass |
| Full topology contract | `1 passed` trong `17.64s` |
| Demo decision | `GO` |

Evidence được ghi nhận ngày `2026-08-27`, commit
`d9b11f4bfcf34cffa6cb37812ebda69f84e079fe`, dùng local mock-data. Demo reset
chỉ dành cho local vì fixture xóa dữ liệu MongoDB/PostgreSQL.

## Demo flow

| Bước | Kết quả cần kiểm tra |
|---|---|
| Start Compose và reset fixture | Có source file `DEMO`, schedule `DEMO1`, dữ liệu local sạch |
| Chạy scheduler-first flow | Tạo pending `ReviewPacket`, sau approval chạy quality gate |
| Xử lý `DEMO` | Row hợp lệ persist; invalid row quarantine; conflict giữ source unit |
| Xử lý Quarantine tab | Claim và resolve/reject bằng actor `demo-operator` |
| Proceed sau row cuối | Operator chọn `Proceed to reconciliation`; run tiếp tục một lần |
| Chạy `DEMO1` trực tiếp | Thiếu `status` → `BATCH_FATAL` trước row-level quarantine |

| Demo case | Expected result |
|---|---|
| `DEMO-VALID-001-TX` | Persist và có trong reconciliation |
| `DEMO-DUPLICATE-001-TX` | Conflict `HIGH`; claim và resolve |
| `DEMO-MISSING-AMOUNT-001-TX` | Missing required `amount`; reject hoặc reprocess |
| `DEMO-VALID-002-TX` … `DEMO-VALID-018-TX` | Rows hợp lệ cho reconciliation |
| `DEMO1-BATCH-FATAL-001-TX` … `DEMO1-BATCH-FATAL-020-TX` | Dừng tại file gate; không quarantine row |

## Required scenarios

| Scenario | Expected outcome |
|---|---|
| Clean baseline | `PASS / CONTINUE / INGESTED`; counters reconcile; không có quarantine row |
| Ordinary invalid row | `REVIEW / CONTINUE`; row hợp lệ persist |
| Conflicting duplicate | `REVIEW / HOLD_FOR_REVIEW`; source unit bị hold |
| Source-unit recovery | Resume từ checkpoint; không replay conflict |
| Claim race | Một operator thắng; loser nhận bounded conflict |
| Reprocess/accept-existing | Đúng claimant; source/fingerprint verification giữ nội bộ |
| Reject/escalation | Reject có reason; escalation dừng ở level 3 |
| Action replay | Cùng `(recordId, actionId)` không tạo transition/audit thứ hai |
| Redaction | Không lộ raw row, credential, full exception, parsed timestamp hoặc fingerprint |

## Chạy local demo

```bash
docker compose up -d --build --wait postgres mongodb api
make quarantine-demo-reset
make quarantine-demo-run
cd frontend-next && npm run dev
```

Browser checks:

```bash
npm --prefix frontend-next run lint
npm --prefix frontend-next run typecheck
npm --prefix frontend-next run build
npm --prefix frontend-next run test:e2e -- e2e/quarantine-review.spec.ts --workers=1
npm --prefix frontend-next run test:e2e -- e2e/quarantine-demo-live.spec.ts --workers=1
```

## Decision rule và handoff

`GO (demo-only)` cần automated gates, local topology, P0 data-integrity và
redaction đều đạt. `NO-GO` nếu có data loss, duplicate persistence, sai
quality outcome, sai checkpoint ordering, ownership bypass hoặc lộ dữ liệu nhạy
cảm.

Handoff chỉ gồm outcome/counter, quarantine metadata, correlation ID bounded,
acceptance gap và các quyết định observability chưa chốt. Sprint 4 sở hữu phần
triển khai observability.
