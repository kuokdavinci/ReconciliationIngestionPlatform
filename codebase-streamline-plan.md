# Kế hoạch Tinh gọn & Tối ưu hóa Codebase (Codebase Streamlining Plan)

> **Trạng thái cập nhật 2026-08-17:** Phần refactor Phase 2 đã được triển khai
> và push trong commit `9fd20e9`. Các mục còn để `[ ]` là phần chưa thực hiện
> hoặc chưa có đủ evidence để khẳng định hoàn tất; Sprint 3/EDA nằm ngoài
> scope của kế hoạch này.

## Mục tiêu (Goal)
Tinh gọn kiến trúc mã nguồn Backend, loại bỏ các thư mục/file thừa, dọn dẹp và chuẩn hóa bộ Test Suite (~23.5k SLOC) để giảm gánh nặng bảo trì (maintenance burden), tăng tốc độ chạy kiểm thử, đồng thời **giữ nguyên cấu trúc thư mục `docs/` theo đúng chủ đích của dự án**.

---

## Danh sách Hạng mục Thực hiện (Tasks Breakdown)

### Giai đoạn 1: Dọn dẹp Thư mục Wrapper & File tạm ở Cấp Root
- [x] **Task 1.1**: Kiểm tra và loại bỏ 2 thư mục wrapper thừa ở cấp root: [`api/`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/api) (`api/server.py`) và [`backend/`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/backend) (`backend/app.py`), chuyển hướng các script hoặc config tham chiếu trực tiếp về [`src.api:create_app`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/api).
  → **Xác minh**: Chạy `uv run pytest` và kiểm tra lệnh khởi chạy FastAPI server chạy bình thường qua `src.api`.
- [ ] **Task 1.2**: Gom các file kế hoạch sprint rải rác ở thư mục gốc (`sprint-3-eda-*.md`, `sprint2-airflow-*.md`, `architecture-migration-plan.md`) vào thư mục lưu trữ thích hợp hoặc giữ gọn gàng theo quy ước.
  → **Xác minh**: Thư mục gốc sạch sẽ, chỉ giữ các file cấu hình chính (`README.md`, `pyproject.toml`, `docker-compose.yml`...).

---

### Giai đoạn 2: Tinh lọc & Chuẩn hóa Bộ Test Suite (`tests/`)
- [x] **Task 2.1**: Loại bỏ nhóm 13 file `test_*_architecture.py` mang tính hình thức (chỉ assert tên module và chuỗi import của Python, không kiểm tra business logic):
  * `test_indexes_architecture.py`, `test_audit_architecture.py`, `test_checkpoint_architecture.py`
  * `test_fetch_config_architecture.py`, `test_ingestion_architecture.py`, `test_partner_transaction_architecture.py`
  * `test_postgres_architecture.py`, `test_reconciliation_architecture.py`, `test_review_architecture.py`, `test_runtime_architecture.py`, `test_source_unit_architecture.py`, `test_transaction_architecture.py`.
  → **Xác minh**: Không làm mất bất kỳ assertion logic nghiệp vụ nào, giảm hơn 2,000 dòng test giòn (brittle).
- [ ] **Task 2.2**: Xử lý các file test demo/sprint cũ đã hoàn thành nhiệm vụ:
  * Đánh giá và loại bỏ/gộp các file: `test_sprint1_eval_benchmark.py`, `test_sprint2_ui_demo.py`, `test_viettelpay_sprint2_demo.py`, `test_vnpay_filedrop_backfill_demo.py`, `test_phase8.py`, `test_phase20.py`, `test_legacy_scheduler_removed.py`.
  * Chuyển các test case nghiệp vụ hợp lệ còn giá trị sang các file test chức năng tương ứng trong `tests/`.
  → **Xác minh**: Bộ test chạy nhanh hơn, không còn test demo dư thừa.
- [ ] **Task 2.3**: Tập trung hóa Fixtures & Mocks dùng chung vào [`tests/conftest.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/tests/conftest.py):
  * Chuyển các hàm `_create_test_app()`, class `_AsyncCursor`, và MongoDB/Postgres mock sessions đang bị copy-paste rải rác sang fixtures chuẩn của `pytest`.
  → **Xác minh**: Loại bỏ trùng lặp code mock, các file test API trở nên ngắn gọn và dễ đọc.

---

### Giai đoạn 3: Hợp nhất & Tinh gọn Tầng Application ([`src/application/`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/application))
- [ ] **Task 3.1**: Tinh gọn sub-module `src/application/automation`:
  * Gom các file nhỏ lẻ vụn vặt (18-40 dòng như `stream_review_gate.py`, `stream_staging.py`, `stream_fetching.py`, `workflows.py`) vào các runner/service chính (`stream_runner.py`, `backfill_service.py`, `service.py`).
  → **Xác minh**: Giảm số lượng file rời rạc từ 21 file xuống còn ~6-8 file mạch lạc.
- [ ] **Task 3.2**: Tinh gọn sub-module `src/application/review`:
  * Hợp nhất các helper phụ (`errors.py`, `evidence.py`, `mapping_support.py`, `scope_support.py`) vào module xử lý workflow chính (`mapping_workflow.py`, `actions.py`, `proposal_creation.py`).
  → **Xác minh**: Luồng code review rõ ràng, giảm lớp trung gian (indirection).

---

### Giai đoạn 4: Kiểm thử Toàn diện & Xác thực Hậu Tái cấu trúc
- [ ] **Task 4.1**: Chạy toàn bộ test suite để đảm bảo 100% test cases còn lại đều PASS:
  * Lệnh kiểm tra: `pytest -v` (áp dụng chuẩn FastAPI/Starlette httpx2/AsyncClient theo hướng dẫn AGENTS.md).
  → **Xác minh**: Toàn bộ test suite vượt qua (0 failures), thời gian chạy test giảm.
- [x] **Task 4.2**: Cập nhật lại codegraph index (`.codegraph/codegraph.db`) và đo lường lại số lượng dòng code (LOC & SLOC) sau khi tối ưu.

---

## Tiêu chí Hoàn thành (Done When)
- [x] Thư mục gốc sạch sẽ, loại bỏ các wrapper không cần thiết (`api/`, `backend/`).
- [x] Cấu trúc `docs/` được **giữ nguyên vẹn 100% theo đúng ý định của bạn**.
- [ ] Bộ test suite được tinh giản, loại bỏ các file test ảo/demo/trùng lặp, code test gọn gàng và chạy nhanh hơn.
- [ ] Tầng `src/application/` được gom nhóm mạch lạc, dễ truy vết logic.
- [ ] Toàn bộ hệ thống test và API hoạt động bình thường, không lỗi phát sinh.
