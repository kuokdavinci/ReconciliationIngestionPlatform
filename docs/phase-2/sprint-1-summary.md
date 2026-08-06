# Sprint 1 Summary Report (Idempotency, Pipeline Performance & UI Alignment)

> **Phase 2 - Sprint 1 Summary & Technical Overview**  
> **Trạng thái**: ✅ **COMPLETED & VERIFIED (100% Core Requirements & E2E Flow)**

---

## 🎯 1. Các Tính Chất & Chức Năng Đã Thêm (Core Properties & Features)

Sprint 1 tập trung giải quyết bài toán **Tính An Toàn Dữ Liệu (Idempotency & Duplicate Prevention)**, **Đồng Bộ Kiến Trúc Lưu Trữ (PostgreSQL Primary)**, **Pipeline Performance Metrics** và **Trực Quan Hóa Luồng Đối Soát trên UI**.

### Các Tính Chất Cốt Lõi (Core Properties):
1. **Strict Idempotency & Conflict-Safe Ingestion**: 
   - Đảm bảo tính bất biến: 1 file hoặc batch nạp nhiều lần không sinh ra dữ liệu trùng lặp trong Database.
   - Xử lý mượt mà bài toán partial re-upload (nộp lại file chứa 50 dòng cũ + 50 dòng mới) nhờ cơ chế `ON CONFLICT DO NOTHING` trên PostgreSQL.
2. **PostgreSQL Single Source of Truth**:
   - Chuyển đổi 100% dữ liệu giao dịch (`internal_transaction` và `partner_transaction`) sang PostgreSQL.
   - Loại bỏ hoàn toàn fallback lưu trữ Data Container trên MongoDB, MongoDB chỉ dùng làm Metadata/Config store.
3. **Multi-Stage Claim Protection**:
   - Bảo vệ 2 lớp chống claim trùng: Lớp 1 ở File Level bằng `fileHash` (SHA256), Lớp 2 ở Ingestion Level bằng `FetchUnitKey`.

### Các Chức Năng Mới Đã Thêm (New Features):
1. **Dynamic Pipeline Metrics Dashboard (Frontend & API)**:
   - Thêm khối thống kê hiệu năng Pipeline realtime trên giao diện Reconciliation (`/reconciliation`): Total Ingested Records, Normalized Valid Rows, Ingestion Throughput (`0.45s ~44 rec/s`), và Duplicate/Missing Rows.
2. **Guided Wizard Step 4 (Approve & Execute)**:
   - Tích hợp Step 4 vào Popup AI Assist / Mapping Studio cho phép thực hiện 3 bước liên hoàn trong 1 click: `Approve Mapping Config` ➔ `Trigger Ingestion` ➔ `Run Reconciliation`.
3. **Automated E2E Seeding Alignment (`make momo-e2e-reset`)**:
   - Cập nhật script nạp dữ liệu demo xóa/ghi `internal_transaction` trên PostgreSQL source of truth, tự động sinh 20 bản ghi khớp 1-1 giữa Postgres Internal DB và File Excel của Partner.

---

## 📂 2. Các Thay Đổi Cốt Lõi Và Các File Ảnh Hưởng (Core File Map)

| Thành Phần System | Các File Ảnh Hưởng Chính | Vai Trò & Thay Đổi Cốt Lõi |
|---|---|---|
| **Database Schema** | [`alembic/versions/0002_ingestion_key_unique.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/alembic/versions/0002_ingestion_key_unique.py)<br>[`src/models/postgres.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/models/postgres.py) | Thêm cột `ingestion_key` NOT NULL và tạo Unique Constraint `(identify, ingestion_key)` trên PostgreSQL. |
| **Data Models & Repos** | [`src/models/data_container.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/models/data_container.py)<br>[`src/models/internal_transaction.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/models/internal_transaction.py)<br>[`src/models/reconciliation_result.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/models/reconciliation_result.py) | Chuyển toàn bộ truy vấn CRUD dữ liệu giao dịch sang PostgreSQL SQLAlchemy Async Engine. |
| **Ingestion Pipeline** | [`src/pipeline/ingestion_pipeline.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/pipeline/ingestion_pipeline.py) | Thực thi chèn batch dữ liệu conflict-safe `ON CONFLICT (identify, ingestion_key) DO NOTHING`. |
| **Backend API** | [`src/api/reconciliation.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/api/reconciliation.py)<br>[`src/api/automation.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/src/api/automation.py) | Cung cấp API trạng thái chạy, filter theo date/source_file_id và bắt buộc kiểm tra actor `X-Actor`. |
| **Frontend UI** | [`frontend-next/src/app/reconciliation/page.tsx`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/frontend-next/src/app/reconciliation/page.tsx)<br>[`frontend-next/src/components/reconciliation/run-status-panel.tsx`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/frontend-next/src/components/reconciliation/run-status-panel.tsx)<br>[`frontend-next/src/components/mapping-studio/mapping-studio-execute-step.tsx`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/frontend-next/src/components/mapping-studio/mapping-studio-execute-step.tsx) | Bổ sung Pipeline Metrics Dashboard, liên kết số liệu thực tế từ Backend và bổ sung Step 4 Execute Wizard. |
| **Seeding & Tools** | [`scripts/demo/sprint1/seed_momo_e2e.py`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/scripts/demo/sprint1/seed_momo_e2e.py)<br>[`Makefile`](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/Makefile) | Wipe/seed `internal_transaction` qua PostgreSQL source of truth, hỗ trợ tham số `--file-dir mock_data`. |

---

## ⚡ 3. Các Method/Function Quan Trọng (Key Technical Methods)

1. `IngestionPipeline._insert_postgres_batch(rows)`:
   - **Chức năng**: Chèn danh sách bản ghi giao dịch đã chuẩn hóa vào PostgreSQL bằng câu lệnh `INSERT ... ON CONFLICT DO NOTHING`.
   - **Tác dụng**: Giúp pipeline nuốt dữ liệu tốc độ cao mà không bị nghẽn hay crash khi gặp bản ghi trùng lặp.
2. `ReconciliationEngine.reconcile(partner, reconciliation_date)`:
   - **Chức năng**: Khởi chạy thuật toán đối soát 2 chiều giữa Postgres `internal_transaction` và `partner_transaction`.
   - **Tác dụng**: Phân loại kết quả thành `MATCHED`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `MISSING_PARTNER`, `MISSING_INTERNAL`.
3. `_seed_internal(keys, day)`:
   - **Chức năng**: Khởi tạo bản ghi giao dịch nội bộ qua `InternalTransactionRepository` trên PostgreSQL, bỏ qua source key đã tồn tại.
4. `_full_wipe(db)`:
   - **Chức năng**: Dọn dẹp sạch toàn bộ các collection trên MongoDB và các bảng trên PostgreSQL của Partner trước khi thực hiện reset demo.

---

## 🧪 4. Danh Sách Test Scenarios (Eval & Benchmark Catalog)

Bộ kiểm thử tích hợp (Eval Suite) bao gồm **13 Test Scenarios** chạy trên PostgreSQL & MongoDB thực tế:

| Mã Scenario | Tên Kịch Bản Kiểm Thử | Tác Dụng & Tiêu Chí Nghiệm Thu | Kết Quả |
|---|---|---|---|
| `SCENARIO-00` | **Hợp Đồng Schema PostgreSQL** | Cột `ingestion_key` là `NOT NULL` và Unique Constraint `(identify, ingestion_key)` tồn tại. | ✅ PASS |
| `SCENARIO-01` | **Nạp File Ban Đầu (100 Dòng)** | Nạp 100 dòng mới hợp lệ ➔ Ghi nhận 100 bản ghi chèn mới, 0 trùng lặp. | ✅ PASS |
| `SCENARIO-02` | **Chống Nộp Trùng File (File Replay)** | Replay cùng file Excel (SHA256 trùng) ➔ Chặn ở bước File Claim, từ chối nạp lại. | ✅ PASS |
| `SCENARIO-03` | **Batch Trùng Một Phần (ON CONFLICT)** | Nạp file chứa 50 dòng cũ + 50 dòng mới ➔ Chèn 50 dòng mới, skip 50 dòng cũ safe-conflict. | ✅ PASS |
| `SCENARIO-04` | **Batch Trùng 100% (File Tên Khác)** | Nạp file tên mới nhưng chứa 100 dòng trùng ➔ Không sinh thêm dòng trùng lặp nào trong DB. | ✅ PASS |
| `SCENARIO-05` | **Giao Dịch Khác Ingestion Key** | 2 giao dịch chỉ khác `ingestion_key` ➔ Chèn đủ 2 dòng độc lập. | ✅ PASS |
| `SCENARIO-06` | **Bất Biến Trùng Lặp Database** | Kiểm tra trực tiếp DB: Số nhóm trùng lặp identity `(identify, ingestion_key) = 0`. | ✅ PASS |
| `SCENARIO-07` | **Tranh Chấp Claim File Đồng Thời** | 2 Worker cùng claim 1 file SHA256 ➔ Đúng 1 Worker claim thành công. | ✅ PASS |
| `SCENARIO-08` | **Chống Nộp Trùng Fetch-Unit API** | Replay cùng 1 Fetch-Unit API ➔ Chặn trùng lặp cấp độ API. | ✅ PASS |
| `SCENARIO-09` | **Từ Chối Thiếu Ingestion Key** | Payload thiếu thông tin định danh ➔ Báo lỗi `ValueError`, không sinh key ngẫu nhiên. | ✅ PASS |
| `SCENARIO-10` | **Hợp Đồng Kế Toán Lỗi Non-Duplicate** | Phân định rõ lỗi dữ liệu thường và lỗi trùng lặp. | ✅ PASS |
| `SCENARIO-11` | **An Toàn Migration Data Lịch Sử** | Đảm bảo migration an toàn trên DB live. | ✅ PASS |
| `SCENARIO-12` | **Lưu Trữ Transaction Thuần PostgreSQL** | Kiểm tra 100% giao dịch nằm ở Postgres, không dùng fallback Mongo. | ✅ PASS |

---

## 🎬 5. Kịch Bản Demo Hiện Tại (Demo Scenario Catalog)

Hệ thống hiện tại hỗ trợ 3 kịch bản Demo hoàn chỉnh được đóng gói sẵn qua `Makefile`:

### Kịch Bản 1: End-to-End Dynamic Ingestion & Matching (`make momo-e2e-reset`)
- **Mục đích**: Demo toàn bộ luồng từ khi file về, đi qua Review Center/Step 4 Guided Wizard cho đến khi thực thi Ingestion & Reconciliation.
- **Các bước thực hiện**:
  1. Gõ `make momo-e2e-reset` ➔ Reset sạch DB cũ, sinh 20 dòng Postgres DB nội bộ + file `settlement_MOMO_20260731.xlsx` tại `./mock_data` + Mapping Config trạng thái `PENDING_APPROVAL`.
  2. Truy cập `/schedules` bấm **Run Now** (hoặc mở Guided Wizard Popup Step 4).
  3. Hệ thống tạo **Pending Review Packet** (Hiển thị `1 pending`).
  4. Bấm **Approve & Activate** ➔ Tự động nạp 20 dòng vào Postgres ➔ Chạy Reconciliation Engine ➔ Đạt kết quả **100% MATCHED**!

### Kịch Bản 2: Idempotency & Partial Re-Upload Check (`make momo-e2e-phase2`)
- **Mục đích**: Chứng minh tính năng chống nộp trùng dòng và tính Idempotency khi nạp đè dữ liệu.
- **Các bước thực hiện**:
  1. Gõ `make momo-e2e-phase2` ➔ Nạp thêm 20 bản ghi đợt 2 (`WAVE 2`).
  2. Chạy lại Ingestion Pipeline ➔ Kiểm tra DB chỉ chèn đúng 20 dòng mới, 20 dòng cũ không bị nạp trùng.

### Kịch Bản 3: Discrepancy & Missing Partner Review (`make momo-e2e-missing-partner-demo`)
- **Mục đích**: Demo khả năng phát hiện lệch dữ liệu giữa Hệ thống nội bộ và Partner.
- **Các bước thực hiện**:
  1. Gõ `make momo-e2e-missing-partner-demo` ➔ Khởi tạo 1 giao dịch nội bộ mà file Partner không có (`MOMO_TXN_90_MISSING_PARTNER`).
  2. Khởi chạy đối soát ➔ Trang Reconciliation ngay lập tức phát hiện 1 bản ghi **`MISSING_PARTNER`** và đề xuất giải pháp xử lý.
