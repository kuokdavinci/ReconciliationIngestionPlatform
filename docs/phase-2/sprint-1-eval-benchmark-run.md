# Báo cáo Benchmark và Đánh giá Sprint 1 (Idempotency và Ngăn ngừa Trùng lặp)

> **Môi trường thử nghiệm**: PostgreSQL transaction store thật (`reconciliation_test`) và MongoDB metadata store thật
> **Thời điểm thực thi**: 2026-08-11 15:42:11 UTC
> **Kết quả đánh giá tổng quan**: ✅ **PASS (100%)** (13/13 kịch bản PASS)

---

## 🎯 1. Mục tiêu đánh giá và tiêu chí nghiệm thu Sprint 1

Báo cáo này đo lường và xác nhận các cơ chế thuộc **Sprint 1 (Idempotency và Ngăn ngừa Trùng lặp)** hoạt động chính xác trên môi trường thực tế, đáp ứng đầy đủ các tiêu chí nghiệm thu:
1. **PostgreSQL Schema & Unique Constraint**: Cột `ingestion_key` duy nhất theo `(identify, ingestion_key)` và NOT NULL.
2. **File Replay & Fetch-Unit Claim Protection**: Chống nộp trùng file (Hash SHA256) và trùng Fetch-Unit API.
3. **ON CONFLICT Batch Insertion**: Xử lý chèn dữ liệu conflict-safe tại DB thật mà không crash job.
4. **Data Isolation & Duplicate Invariant**: Đảm bảo 0 nhóm ghi trùng dòng, phân định rõ ràng lỗi `file_duplicate`, `transaction_duplicate`, `batch_conflict`.
5. **Architectural Isolation**: Đưa 100% dữ liệu transaction về PostgreSQL, loại bỏ hoàn toàn fallback Mongo cho data container.
6. **Robustness & Deterministic Key Derivation**: Tính toán key định danh ổn định, từ chối payload thiếu thông tin định danh và đảm bảo migration an toàn.

---

## 📋 2. Danh mục kịch bản và dữ liệu đầu vào

Dưới đây là danh mục dữ liệu đầu vào và đầu ra mong muốn cho từng kịch bản trước khi tiến hành benchmark:

| Mã kịch bản | Tên kịch bản | Dữ liệu đầu vào | Đầu ra mong muốn | Ý nghĩa / mục đích kiểm thử |
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

## 📊 3. Ma trận benchmark và thực thi

Bảng dưới đây tổng hợp kết quả đo đạc thực tế sau khi chạy toàn bộ kịch bản trên PostgreSQL và MongoDB thật:

| Mã kịch bản | Tên kịch bản | Kết quả kỳ vọng | Kết quả thực tế | Trạng thái | Thời gian phản hồi |
|---|---|---|---|---|---|
| `SCENARIO-00` | **Hợp Đồng Schema PostgreSQL** | `Cột ingestion_key là NOT NULL và Unique Constraint tồn tại` | `is_nullable=NO, constraint_exists=True` | ✅ PASS | 16.19 ms |
| `SCENARIO-01` | **Nạp File Ban Đầu (100 Dòng)** | `Đã chèn: 100, Trùng lặp: 0, Thất bại: 0, Trạng thái File: COMPLETED` | `Đã chèn: 100, Trùng lặp: 0, Thất bại: 0, Trạng thái File: COMPLETED` | ✅ PASS | 66.36 ms |
| `SCENARIO-02` | **Chống Nộp Trùng File (File Replay)** | `Tổng số dòng: 0, Mã lỗi: file_duplicate, Số dòng DB giữ nguyên: 100` | `Tổng số dòng: 0, Mã lỗi: file_duplicate, Số dòng DB giữ nguyên: 100` | ✅ PASS | 6.64 ms |
| `SCENARIO-03` | **Batch Trùng Một Phần (ON CONFLICT)** | `Đã chèn: 50, Trùng lặp: 50, Thất bại: 0, Tổng bản ghi DB: 150` | `Đã chèn: 50, Trùng lặp: 50, Thất bại: 0, Tổng bản ghi DB: 150` | ✅ PASS | 70.75 ms |
| `SCENARIO-04` | **Batch Trùng 100% (File Tên Khác)** | `Đã chèn: 0, Trùng lặp: 100, Thất bại: 0, Tổng bản ghi DB: 150` | `Đã chèn: 0, Trùng lặp: 100, Thất bại: 0, Tổng bản ghi DB: 150` | ✅ PASS | 60.34 ms |
| `SCENARIO-05` | **Giao Dịch Khác Ingestion Key** | `Đã chèn: 2, Trùng lặp: 0, Tổng bản ghi DB: 152` | `Đã chèn: 2, Trùng lặp: 0, Tổng bản ghi DB: 152` | ✅ PASS | 19.88 ms |
| `SCENARIO-06` | **Bất Biến Trùng Lặp Database** | `Số nhóm trùng lặp identity (identify, ingestion_key): 0` | `Số nhóm trùng lặp identity: 0` | ✅ PASS | 6.16 ms |
| `SCENARIO-09` | **Từ Chối Khi Thiếu Ingestion Key** | `Báo lỗi ValueError; Không sinh key ngẫu nhiên` | `Unable to derive ingestion_key from transaction payload` | ✅ PASS | 0.02 ms |
| `SCENARIO-10` | **Hợp Đồng Kế Toán Lỗi Non-Duplicate** | `Ghi nhận chính xác failed_rows và mã lỗi batch_conflict` | `failed_rows=True, batch_conflict=True` | ✅ PASS | 0.79 ms |
| `SCENARIO-11` | **An Toàn Migration Data Lịch Sử** | `Kịch bản SCENARIO-00 và SCENARIO-06 đều PASS` | `Kiểm tra schema và bất biến trùng lặp hoàn tất thành công` | ✅ PASS | 0 ms |
| `SCENARIO-12` | **Lưu Trữ Transaction Thuần PostgreSQL** | `Không dùng fallback collection Mongo cho dữ liệu giao dịch` | `postgres_only=True` | ✅ PASS | 0.63 ms |
| `SCENARIO-07` | **Tranh Chấp Claim File Đồng Thời** | `Chính xác 1 claim thành công (created=1) và 1 bị từ chối trùng lặp` | `Số worker tạo thành công=1, Kết quả outcomes=[True, False]` | ✅ PASS | 13.2 ms |
| `SCENARIO-08` | **Chống Nộp Trùng Fetch-Unit API** | `Lần 1 tạo thành công; Lần nộp lại trả về bản ghi fetch-unit đã tồn tại` | `first_created=True, replay_created=False, canonical_file_hash=benchmark-fetch-a-66808f51e560451b9d5e16fa2cd10e17` | ✅ PASS | 9.47 ms |

---

## 📌 4. Kết luận và tiêu chí nghiệm thu Sprint 1

- [x] **1. Hợp đồng Schema**: PostgreSQL constraint `(identify, ingestion_key)` và NOT NULL cột `ingestion_key` vận hành chính xác.
- [x] **2. Chống trùng file & Fetch-unit**: Đạt 100% ở bước claim nhờ SHA256 File Hash và Unique FetchUnitKey index.
- [x] **3. Xử lý duplicate batch conflict**: Phân định rõ ràng giữa `file_duplicate`, `transaction_duplicate`, `batch_conflict` và `fetch_unit_replay`.
- [x] **4. Độ tin cậy dữ liệu**: Dữ liệu DB được bảo vệ tuyệt đối khỏi vỡ duplicate khi retry hoặc upload đè (Invariant duplicates = 0).
- [x] **5. Kiến trúc dữ liệu**: Đạt 100% lưu trữ Transaction trên PostgreSQL, không còn fallback Mongo cho data container.
- [x] **6. An toàn Migration & Derivation**: Tự động từ chối payload không sinh được key, đảm bảo migration an toàn trên DB live.

*Báo cáo được khởi tạo tự động bởi Integration Eval Suite.*
