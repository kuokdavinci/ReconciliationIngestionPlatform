# Báo cáo performance tracing: Ingestion & Reconciliation Pipeline

Tài liệu này ghi lại implementation của performance tracing, baseline
measurement, bottleneck đã chẩn đoán, optimization đã áp dụng và kết quả của
benchmark 100k record.

## 1. Baseline performance và bottleneck

### Baseline timing (trước optimization)
Trước khi thêm performance tracing và áp dụng optimization, pipeline có các đặc
điểm sau:
* **Ingestion (100k ZALOPAY rows):** ~30.0 seconds (3,331 records/sec)
* **Reconciliation (100k matched rows):** ~20.5 seconds (4,870 records/sec)

### Bottleneck đã chẩn đoán
Thông qua structured tracing log mới (`PERF_INGEST` và `PERF_RECON`), các
bottleneck cụ thể được xác định như sau:

1. **Overhead khi parse XML và match string của Excel (Ingestion):**
   * *Evidence:* `read_file_ms` (workbook load) mất khoảng 15.5 giây, còn `parse_rows_ms` mất khoảng 4.5 giây.
   * *Nguyên nhân:* Read-only parser pure-Python của Openpyxl bị giới hạn bởi CPU và chậm. Parser còn kiểm tra mọi cell trên 40 column để tìm footer/summary keyword.
   
2. **Overhead serialization/deserialization của Pydantic (Reconciliation):**
   * *Evidence:* `unmatched_detection_ms` mất khoảng 6.5 giây và `result_bulk_write_ms` mất khoảng 10.7 giây.
   * *Nguyên nhân:* Việc tạo và serialize 100,000 Pydantic model `ReconciliationResult` qua `.model_dump()` cùng recursive type conversion (`_convert_special_types`) trong repository helper tạo CPU overhead rất lớn khi write database.

3. **Lookup key sai/không khớp (Reconciliation):**
   * *Evidence:* `matched_count` ban đầu bằng 0, khiến toàn bộ 100k row bị coi là thiếu partner/internal record.
   * *Nguyên nhân:* Mapped key config bị lệch. ZALOPAY Excel mapping gắn column 11 (`zpMaHDon`) với `trace`, trong khi internal transaction dùng `zpTransId` làm matching key. Engine lookup vì vậy thất bại và phải tạo unmatched array qua các vòng lặp CPU lớn.

---

## 2. Optimization đã áp dụng

### A. Tối ưu summary pattern search trong Excel reader
* Giới hạn summary/footer check ở ba column đầu của mỗi row (`row[:3]`) vì summary marker như "Total" hoặc "Footer" không nằm ở column 40.
* Pre-compile toàn bộ skip pattern thành lowercase khi khởi tạo reader để tránh lặp `.lower()` trong nested cell loop.
* **Tác động:** Giảm hơn 90% tổng số CPU comparison operation ở parse stage.

### B. Bypass Pydantic validation khi MongoDB bulk write (Fast Mode)
* Thêm toggle `fast_mode` cho `ReconciliationEngine`.
* Khi bật `fast_mode` (được kích hoạt ở production API trigger, scheduler job và approve reprocessing flow):
  * Engine thu thập raw Python dictionary thay cho việc tạo `ReconciliationResult` Pydantic object.
  * Write vào MongoDB bỏ qua model-dump loop của `BaseRepository.insert_many` và gọi trực tiếp `collection.insert_many()` sau khi convert Decimal value.
* **Tác động:** Giảm khoảng 50% CPU serialization và bulk write time.

### C. Căn chỉnh matching key cho ZALOPAY config
* Sửa seeded ZALOPAY mapping config để map `zpMaHDon` tới `extra.zpMaHDon` thay vì `trace`.
* Field `trace` vì vậy rỗng (`None`), khiến `_resolve_partner_txn_id` fallback về `pd.id` (`zpTransId`) và khớp với internal transaction.
* **Tác động:** Match thành công 99,989 transaction và loại bỏ path tạo unmatched Pydantic.

### D. Migration sang Calamine Excel parser chạy trên Rust
* Thay library pure-Python `openpyxl` bằng `python-calamine` (Excel parser rất nhanh viết bằng Rust).
* Viết lại method của `ExcelStreamReader` để hỗ trợ Calamine worksheet; helper làm sạch cell (`''` map thành `None`, whole float thành `int` cho monetary và ID value).
* **Tác động:** Giảm Excel load time (`read_file_ms`) từ khoảng 15.5 giây xuống khoảng 1.07 giây (nhanh hơn 14.5 lần).

---

## 3. Bảng so sánh performance

| Stage | Records | Before (Baseline) | After (Optimized) | Current Run (Latest) | Records/sec Before | Records/sec After | Records/sec Current |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ingestion Pipeline** | 99,997 | 30.013s | 14.359s | **14.525s** | 3,331.7 rec/s | 6,916.3 rec/s | 6,884.3 rec/s |
| **Reconciliation Engine** | 100,004 | 20.720s | 13.436s | **12.172s** | 4,826.4 rec/s | 7,342.5 rec/s | 8,215.7 rec/s |

---

## 4. Risk còn lại và future work
* **Giới hạn network và database write:** DB write operation (`db_insert_ms`) hiện chiếm phần lớn ingestion time (khoảng 5.75 giây), bị giới hạn bởi tốc độ disk/write của MongoDB local.
* **Overhead khi có nhiều column:** File trên 50 column vẫn có parsing overhead. Nên giữ cấu trúc spreadsheet gọn.

### 5. Architectural upgrade option: MongoDB Cluster và PostgreSQL

> **Ghi chú:** Section 6 dưới đây ghi lại kết quả implementation PostgreSQL thực tế.
Sau performance tracing chuyên sâu, có hai hướng chính để scale vượt bottleneck MongoDB local:

#### A. MongoDB Cluster / Sharding
- **Mô tả:** Phân phối write trên sharded MongoDB cluster hoặc MongoDB Atlas managed service.
- **Ưu điểm:** Giữ schema-less document architecture của `DataContainer` model, dễ điều chỉnh mapping config.
- **Nhược điểm:** Vẫn có write network/cluster roundtrip overhead và Reconciliation vẫn bị giới hạn bởi Python memory/CPU.

#### B. PostgreSQL (Recommended)
- **Mô tả:** Migration core transactional data (`DataContainer`, `InternalTransaction`, `ReconciliationResult`) sang PostgreSQL.
- **Ưu điểm:**
  - **Ingestion tốc độ cao:** PostgreSQL native `COPY` (qua `asyncpg` `copy_records_to_table`) bỏ qua SQL parsing khi bulk write và có thể insert 100k row trong **khoảng 1 giây**.
  - **Reconciliation trong database:** Thay Python-in-memory matching loop và 100k bulk write bằng một SQL `LEFT JOIN`, giảm matching/write time từ **12.17s xuống dưới 1.0s**.
- **Nhược điểm:** Cần schema mapping và migration rõ ràng.

---

## 6. Kết quả PostgreSQL in-database reconciliation (mới nhất)

Sau migration sang PostgreSQL, nhóm đã chạy reproducible benchmark 100k và áp
dụng `UNLOGGED` table optimization cho staging/transaction data. Kết quả như sau:

| Stage | Records | MongoDB Optimized | PostgreSQL (Initial) | PostgreSQL (UNLOGGED Opt) | Total Optimization % (vs MongoDB Optimized) | Records/sec (PostgreSQL UNLOGGED) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ingestion Pipeline** | 99,997 | 14.359s | 14.136s | **12.555s** | **+12.6%** | 7,964.7 rec/s |
| **Reconciliation Engine** | 99,997 | 13.436s | 4.577s | **4.577s** | **+65.9%** (3x faster) | 22,160.8 rec/s |

### Cải tiến chính
1. **UNLOGGED table performance (Ingestion):** Đổi `partner_transaction` và `internal_transaction` thành `UNLOGGED` table để bỏ qua WAL write-ahead log nặng. Database write overhead (`db_insert_ms`) giảm **19.0%**, tổng ingestion time từ **14.136s** xuống **12.555s**.
2. **Reconciliation Engine execution:** Chuyển matching logic từ Python memory loop và MongoDB bulk insert sang PostgreSQL native SQL join, giảm stage matching và result writing từ **13.436s** xuống **4.577s** (tiết kiệm **65.9%** hoặc nhanh hơn **3 lần**).
3. **Primary key safety:** Đổi primary key của reconciliation result table sang native UUID generation (`gen_random_uuid()`) để tránh constraint violation khi có duplicate matching scenario.
