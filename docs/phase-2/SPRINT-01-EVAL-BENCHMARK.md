# Sprint 1 Master Evaluation & Benchmark Specification (Plan 1: Idempotency & Duplicate Prevention)

> **Trạng thái**: Tài liệu Mẫu Chuẩn (Master Specification)  
> **Kế hoạch (Plan)**: `PLAN-01-IDEMPOTENCY`  
> **Lệnh sinh báo cáo thực thi**: `./.venv/bin/pytest tests/test_sprint1_eval_benchmark.py -v`  
> **File xuất kết quả runtime**: [SPRINT-01-EVAL-BENCHMARK-RUN.md](file:///home/vsf-quoclta-u/Documents/ReconciliationIngestionPlatform/docs/phase-2/SPRINT-01-EVAL-BENCHMARK-RUN.md)

---

## 🎯 1. Mục tiêu Đánh giá (Sprint 1 Acceptance Criteria)

Báo cáo này đo lường và xác nhận các cơ chế thuộc **Plan 1 (Idempotency & Duplicate Prevention)** hoạt động chính xác trên môi trường thực tế, đáp ứng đầy đủ các tiêu chí nghiệm thu:
1. **PostgreSQL Schema & Unique Constraint**: Cột `ingestion_key` duy nhất theo `(identify, ingestion_key)` và NOT NULL.
2. **File Replay & Fetch-Unit Claim Protection**: Chống nộp trùng file (Hash SHA256) và trùng Fetch-Unit API.
3. **ON CONFLICT Batch Insertion**: Xử lý chèn dữ liệu conflict-safe tại DB thật mà không crash job.
4. **Data Isolation & Duplicate Invariant**: Đảm bảo 0 nhóm ghi trùng dòng, phân định rõ ràng lỗi `file_duplicate`, `transaction_duplicate`, `batch_conflict`.
5. **Architectural Isolation**: Đưa 100% dữ liệu transaction về PostgreSQL, loại bỏ hoàn toàn fallback Mongo cho data container.
6. **Robustness & Deterministic Key Derivation**: Tính toán key định danh ổn định, từ chối payload thiếu thông tin định danh và đảm bảo migration an toàn.

---

## 📋 2. Mô Tả Danh Sách Các Kịch Bản Thử Nghiệm (Scenario Catalog & Inputs)

Ma trận dưới đây định nghĩa toàn bộ 13 Scenarios bắt buộc phải thực thi và kiểm tra:

| Mã Kịch Bản | Tên Kịch Bản | Thông Số Dữ Liệu Input (Inputs) | Đầu Ra Mong Muốn (Output Expectation) | Ý Nghĩa / Mục Đích Kiểm Thử |
|---|---|---|---|---|
| `SCENARIO-00` | **Hợp Đồng Schema PostgreSQL** | Cột ingestion_key và Unique Constraint trên (identify, ingestion_key) | `Cột ingestion_key là NOT NULL và Unique Constraint tồn tại` | Yêu cầu Alembic Migration 0002 đã được áp dụng thành công |
| `SCENARIO-01` | **Nạp File Ban Đầu (100 Dòng)** | File 100 dòng giao dịch mới hợp lệ | `Đã chèn: 100, Trùng lặp: 0, Thất bại: 0, Trạng thái File: COMPLETED` | Nạp 100 dòng hoàn toàn mới vào cơ sở dữ liệu PostgreSQL thật |
| `SCENARIO-02` | **Chống Nộp Trùng File (File Replay)** | Upload lại chính xác file batch_1.xlsx | `Tổng số dòng: 0, Mã lỗi: file_duplicate, Số dòng DB giữ nguyên: 100` | Ngăn chặn nộp trùng file ở cấp độ SHA256 File Hash |
| `SCENARIO-03` | **Batch Trùng Một Phần (ON CONFLICT)** | File mới gồm 50 giao dịch cũ + 50 giao dịch mới | `Đã chèn: 50, Trùng lặp: 50, Thất bại: 0, Tổng bản ghi DB: 150` | Xử lý ON CONFLICT DO NOTHING tại Postgres DB thật, ghi nhận đúng thống kê |
| `SCENARIO-04` | **Batch Trùng 100% (File Tên Khác)** | File tên mới chứa 100 giao dịch đã tồn tại | `Đã chèn: 0, Trùng lặp: 100, Thất bại: 0, Tổng bản ghi DB: 150` | Hoàn thành job thành công (COMPLETED) nhưng không phát sinh bản ghi trùng |
| `SCENARIO-05` | **Giao Dịch Khác Ingestion Key** | 2 giao dịch hợp lệ chỉ khác nhau thuộc tính ingestion_key | `Đã chèn: 2, Trùng lặp: 0, Tổng bản ghi DB: 152` | Xác nhận các dòng dữ liệu không bị gộp nhầm do trùng các trường phi định danh |
| `SCENARIO-06` | **Bất Biến Trùng Lặp Database** | Toàn bộ bản ghi kiểm thử trong bảng partner_transaction | `Số nhóm trùng lặp identity (identify, ingestion_key): 0` | Kiểm tra trực tiếp tính bất biến (Invariant) không trùng lặp trên cơ sở dữ liệu thật |
| `SCENARIO-09` | **Từ Chối Khi Thiếu Ingestion Key** | Payload giao dịch thiếu cả partner id lẫn trace | `Báo lỗi ValueError; Không sinh key ngẫu nhiên` | Đảm bảo hợp đồng trích xuất ingestion_key nghiêm ngặt |
| `SCENARIO-10` | **Hợp Đồng Kế Toán Lỗi Non-Duplicate** | Mã nguồn pipeline và đối tượng thống kê kết quả | `Ghi nhận chính xác failed_rows và mã lỗi batch_conflict` | Kiểm soát các lỗi phát sinh không do trùng lặp dữ liệu |
| `SCENARIO-11` | **An Toàn Migration Data Lịch Sử** | Kiểm tra schema và bất biến trên DB live | `Kịch bản SCENARIO-00 và SCENARIO-06 đều PASS` | Migration đảm bảo an toàn tuyệt đối cho dữ liệu lịch sử |
| `SCENARIO-12` | **Lưu Trữ Transaction Thuần PostgreSQL** | Repository giao dịch partner, internal và kết quả đối soát | `Không dùng fallback collection Mongo cho dữ liệu giao dịch` | MongoDB chỉ dành riêng cho cấu hình và metadata |
| `SCENARIO-07` | **Tranh Chấp Claim File Đồng Thời** | 2 worker cùng claim 1 file hash SHA256 đồng thời | `Chính xác 1 claim thành công (created=1) và 1 bị từ chối trùng lặp` | Unique Index fileHash trên MongoDB là ranh giới chống tranh chấp claim |
| `SCENARIO-08` | **Chống Nộp Trùng Fetch-Unit API** | Cùng 1 endpoint/page đại diện bởi 1 fetchUnitKey duy nhất | `Lần 1 tạo thành công; Lần nộp lại trả về bản ghi fetch-unit đã tồn tại` | Nội dung file khác nhau nhưng chung fetchUnitKey sẽ bị chặn không cho tạo mới |

---

## 📊 3. Bảng Kết Quả Benchmark & Thực Thi (Benchmark Execution Matrix)

*(Phần này được cập nhật động trong file `SPRINT-01-EVAL-BENCHMARK-RUN.md` sau mỗi lần chạy bộ test benchmark).*

Ví dụ cấu trúc bảng kết quả đo đạc:

| Mã Kịch Bản | Tên Kịch Bản | Kết Quả Dự Kiến (Expected) | Kết Quả Thực Tế (Actual) | Trạng Thái | Thời Gian Phản Hồi |
|---|---|---|---|---|---|
| `SCENARIO-00` đến `SCENARIO-12` | *(Hiển thị kết quả run thực tế)* | *(Kỳ vọng)* | *(Thực tế)* | ✅ PASS / ⏭️ SKIP | *ms* |

---

## 📌 4. Kết Luận & Tiêu Chí Nghiệm Thu Cho Sprint 1

Toàn bộ 6 tiêu chí nghiệm thu dưới đây bắt buộc phải đạt trạng thái Check (`[x]`):

- [x] **1. Hợp đồng Schema**: PostgreSQL constraint `(identify, ingestion_key)` và NOT NULL cột `ingestion_key` vận hành chính xác.
- [x] **2. Chống trùng file & Fetch-unit**: Đạt 100% ở bước claim nhờ SHA256 File Hash và Unique FetchUnitKey index.
- [x] **3. Xử lý duplicate batch conflict**: Phân định rõ ràng giữa `file_duplicate`, `transaction_duplicate`, `batch_conflict` và `fetch_unit_replay`.
- [x] **4. Độ tin cậy dữ liệu**: Dữ liệu DB được bảo vệ tuyệt đối khỏi vỡ duplicate khi retry hoặc upload đè (Invariant duplicates = 0).
- [x] **5. Kiến trúc dữ liệu**: Đạt 100% lưu trữ Transaction trên PostgreSQL, không còn fallback Mongo cho data container.
- [x] **6. An toàn Migration & Derivation**: Tự động từ chối payload không sinh được key, đảm bảo migration an toàn trên DB live.

---
*Mẫu tài liệu chuẩn cho Sprint 1 Idempotency Benchmark.*
