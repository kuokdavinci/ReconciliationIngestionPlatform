## Đồng bộ reconciliation logic

### Sprint 3 — chốt contract

- [x] Xác định canonical normalized `reconciliation_key` dùng cho cả hai phía; ghi rõ `partner_trace`/`partner_txn_id` là semantic field còn `vspTransId` chỉ là source input riêng của partner. Xem `docs/phase-2/sprint-3-reconciliation-key-evidence.md`.
- [x] Xác định uniqueness scope của key: `(partner, key)` hoặc `(partner, reconciliation_date, key)`; không thêm `source_file_id` nếu replacement file chỉ đại diện cho cùng logical transaction. Sprint 3 dùng `(partner, reconciliation_key)`.
- [x] Audit dữ liệu partner và internal cho key null/blank, duplicate key và fallback value conflict trước khi thêm constraint. Xem bounded Docker snapshot trong evidence document.
- [x] Xác nhận constraint hiện tại dùng đúng mục đích: `ingestion_key` cho ingest idempotency, `reconciliation_key` cho business matching.
- [x] Ghi duplicate rate, invalid-key rate và contract constraint/index đề xuất làm Sprint 3 acceptance evidence.

### Sau Sprint 3 — triển khai reconciliation path đã thống nhất

Các mục dưới đây vẫn là follow-up migration backlog. Chúng không thuộc
closeout data-quality/quarantine của Sprint 3 vì cần thay đổi PostgreSQL
schema, remediation duplicate, rollout validation và benchmark decision trước
khi enforcement.

- [ ] Thêm normalized `reconciliation_key` được persist vào cả hai transaction model, backfill và validate backfill trước khi enforce constraint.
- [ ] Chỉ thêm unique constraint sau duplicate remediation; giữ version/history model nếu internal transaction có thể được correction hoặc lặp hợp lệ.
- [ ] Thêm index cho access path thực tế, tối thiểu partner/date/key trên cả hai transaction table.
- [ ] Cập nhật PostgreSQL reconciliation query để join bằng canonical key thay vì tính lại fallback logic trong query.
- [ ] So sánh currency cùng amount và status; thêm kết quả `CURRENCY_MISMATCH` khi cần.
- [ ] Tách `PENDING` khỏi status unknown/invalid; status unknown không được trở thành kết quả `MATCHED` thành công.
- [ ] Đưa key blank/invalid vào invalid-key hoặc quarantine outcome rõ ràng thay vì chỉ coi là missing-side record.
- [ ] Phát hiện duplicate key trước join và trả outcome `AMBIGUOUS_MATCH`/duplicate-key; không âm thầm dùng `ROW_NUMBER()` nếu business rule không quy định “latest wins”.
- [ ] Cô lập reconciliation run bằng `reconciliation_run_id` cùng lock hoặc concurrency control tương đương cho cùng partner/date scope.
- [ ] Thu hẹp CTE projection và không load toàn bộ result set vào memory nếu có thể paginate hoặc stream.

### Verification và rollout

- [ ] Thêm unit/integration test cho currency mismatch, unknown status, null key, duplicate key, replacement scope và concurrent runs.
- [ ] Chạy `EXPLAIN (ANALYZE, BUFFERS)` trên dataset full-snapshot và incremental đại diện sau thay đổi schema/query.
- [ ] Backfill và constraint migration phải fail safely với duplicate report; không bật unique constraint khi duplicate chưa được xử lý.
- [ ] Chạy lại benchmark 1M rows và so sánh correctness counters cùng elapsed time/throughput trước khi đổi runtime default.
