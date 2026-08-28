# Sprint 3 — Reconciliation key evidence

**Trạng thái:** Đã đóng contract cho data-quality/quarantine boundary.
Persisted-key migration và constraint rollout là backlog sau Sprint 3.

## Canonical key

| Phía | Canonical field | Scope |
|---|---|---|
| Partner | `partner_trace`; mapping của từng partner cung cấp source identifier | `(partner, reconciliation_key)` |
| Internal | `partner_txn_id` | `(partner, reconciliation_key)` |

`vspTransId` chỉ là partner-specific legacy input. Fallback của partner dùng
thứ tự `partner_metadata.vspTransId` → `partner_id`; giá trị blank bị bỏ qua.
`source_file_id` không phải business-key component. `partner_trace` có ưu tiên
cao nhất; fallback conflict được audit, không tạo key thứ hai.

## Demo data audit

Snapshot bounded từ Docker PostgreSQL ngày 2026-08-28:

| Check | Kết quả |
|---|---:|
| Partner transaction rows | 19 |
| Internal transaction rows | 20 |
| Partner/internal invalid hoặc blank key | 0 / 0 |
| Partner/internal duplicate key group | 0 / 0 |
| Rows trong duplicate key group | 0 / 0 |
| Fallback conflict (`partner_trace` vs `partner_id`) | 1 |
| Unknown partner/internal status | 0 / 0 |
| Currency mismatch trong reconciliation result | 0 |

Fallback conflict được xử lý theo precedence; không có duplicate key group.

## Constraint boundary

| Hiện tại | Sau Sprint 3 |
|---|---|
| `uq_partner_transaction_identify_ingestion_key` bảo vệ ingestion idempotency | Thêm nullable `reconciliation_key`, validate/backfill và remediate duplicate |
| Primary key bảo vệ row identity | Chỉ thêm index/constraint `(partner, reconciliation_key)` sau khi audit sạch |
| Chưa có PostgreSQL/Alembic schema change cho key | Migration phải fail-closed và không chạy trước remediation |

## Verification

| Kiểm tra | Kết quả |
|---|---|
| Full Python suite | `1346 passed, 18 skipped` |
| Focused Sprint 3 regression | `239 passed` |
| Ruff/mypy | Pass; `207 source files` |
| Frontend lint/typecheck/build | Pass |
| Playwright dashboard | `8 passed` |
| Playwright scheduler-first DEMO | `1 passed` |
| Playwright quarantine/batch-fatal | `8 passed` |
| Compose | Pass; API, MongoDB, PostgreSQL healthy |
