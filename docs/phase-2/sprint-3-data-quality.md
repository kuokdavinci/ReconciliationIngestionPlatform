# Plan 3 — EDA, data quality và quarantine

## Mục tiêu

Giữ lại có cấu trúc mọi record bị reject, phân biệt lỗi record với lỗi batch, truy vết được nguồn/config và cho phép reprocess nhóm lỗi mà không chạy lại toàn bộ nguồn. Bổ sung EDA để đánh giá file trước ingestion và cung cấp quality gate có thể giải thích. Không mở rộng sang logic đối soát, frontend hay AI.

## Đối chiếu hiện trạng

- `src/normalizer/normalizer.py` và `src/validators/validator.py` đã trả về lỗi có `field`, `reason`, `row`, `trace`.
- `IngestionPipeline` hiện gom lỗi vào list/log; lỗi không được persist thành quarantine record.
- Lỗi row được continue, nhưng lỗi reader/config/persistence làm file `FAILED`; chưa có severity/phase contract thống nhất.
- `ProcessingStats` mới có `total/success/failed`; chưa phân biệt rejected, duplicate, quarantined và input reconciliation.

## EDA trước ingestion

### Câu hỏi cần trả lời

File settlement của partner có đủ đúng cấu trúc và chất lượng để ingestion/reconciliation an toàn không? Nếu không, lỗi nằm ở field, row, partner hay schema version nào?

### Phạm vi cơ bản

1. Tạo notebook hoặc script reproducible dùng Pandas/NumPy để profile các fixture CSV, Excel và JSON hiện có; không thay thế reader streaming trong production.
2. Chuẩn hóa profile về canonical fields: `transaction_id`, `trace`, `amount`, `status`, `transaction_date`, `currency` sau khi áp dụng mapping tương ứng.
3. Tính các chỉ số: row/column count, datatype, missing rate, duplicate rate, distinct values, amount percentiles, date range và status distribution.
4. Kiểm tra schema drift: missing/new columns, mapping bắt buộc không tồn tại, thay đổi kiểu dữ liệu và thay đổi đáng kể trong phân phối dữ liệu so với baseline.
5. Dùng NumPy/IQR hoặc percentile để gắn cờ amount outlier. Outlier chỉ là cảnh báo/review nếu chưa có ngưỡng business được phê duyệt; không tự động reject chỉ vì khác biệt thống kê.
6. Sinh quality profile gồm `quality_score`, `valid/rejected/duplicate`, các rule pass/fail và quyết định `PASS`, `REVIEW` hoặc `FAIL`.

### Luồng kết quả

```text
raw file → EDA/profile → quality gate
                         ├─ PASS → normalize/validate/persist
                         ├─ REVIEW → mapping/operator review
                         └─ FAIL → batch failure hoặc quarantine
```

EDA chỉ phát hiện drift và chất lượng; không tự thay thế AI mapping. Khi drift được phát hiện, mapping proposal vẫn đi qua flow approval và runtime validation hiện có.

Notebook/script và báo cáo là deliverable bắt buộc của Sprint 3. UI quality dashboard và Airflow orchestration là follow-up, chỉ thực hiện sau khi profile contract và quality rules ổn định.

## Quyết định đề xuất

1. Tạo collection Mongo `ingestion_quarantine_record` cho dữ liệu lỗi linh hoạt và audit-friendly. Lưu raw row đã sanitize, source file/unit, row number/source location, partner, reconciliation date, error phase/severity/code, config version, attempt count, status và timestamps.
2. Phân loại tối thiểu:
   - `BATCH_FATAL`: file không đọc được, schema/structure không phù hợp, thiếu header hoặc lỗi config bắt buộc; dừng trước khi ghi dữ liệu sai.
   - `RECORD_REJECTED`: chỉ record lỗi; quarantine rồi tiếp tục record hợp lệ.
   - `DUPLICATE`: ghi nhận thống kê/idempotency outcome; không coi là invalid data.
3. Quarantine write phải được thực hiện theo batch và có retry/error policy. Nếu quarantine cũng thất bại, không đánh dấu file completed; giữ trạng thái failed để không mất record lỗi.
4. Reprocess dùng `quarantine_id`/query filter và mapping version mới, tạo attempt mới, không xóa lịch sử. Record sửa thành công chuyển `RESOLVED`; vẫn lỗi chuyển `REJECTED` với reason mới.
5. Chuẩn hóa counters: `input = success + rejected + duplicate` (và các record chưa hoàn tất nếu batch đang partial). Không đưa lỗi validation vào log-only path.
6. Quality gate phải sử dụng profile/rule kết quả từ EDA nhưng không làm thay đổi authority của normalizer, validator hoặc mapping approval.

## File dự kiến modified

- `src/models/quarantine_record.py` — model, enum trạng thái/severity/phase và repository.
- `src/models/indexes.py` — index theo file/unit/status/partner và index phục vụ reprocess.
- `src/core/types.py` — mở rộng `ValidationError`/`ProcessingStats` với phase, code, severity và counters.
- `src/normalizer/normalizer.py` — trả error code/phase nhất quán cho lỗi normalize.
- `src/validators/validator.py` — gắn severity/code và phân biệt validation với duplicate.
- `src/pipeline/ingestion_pipeline.py` — persist quarantine theo batch, xử lý fatal-vs-record, cập nhật counters.
- `scripts/eda/partner_quality_profile.py` hoặc `notebooks/eda_partner_quality.ipynb` — profiling fixture và sinh quality profile/report.
- `src/quality/` — các quality rule deterministic dùng chung sau khi thử nghiệm trong EDA; không đặt trong `src/analysis/` để tránh trộn với AI insights sau đối soát.
- `src/models/reconciliation_file.py` — lưu rejected/duplicate/quarantine counts và trạng thái batch.
- `src/api/automation.py` hoặc router ingestion mới — endpoint vận hành reprocess quarantine; chỉ thêm API backend tối thiểu, không làm frontend.
- `tests/test_validator.py`, `tests/test_normalizer.py`, `tests/test_ingestion_integration.py`, `tests/test_models.py` — test quarantine persistence, fatal structure, partial batch và reprocess.
- `tests/test_data_quality_profile.py` — test profile, schema drift, missing/duplicate, outlier flag và quality decision trên fixture.

## File không thuộc scope

Không sửa `src/reconciliation/engine.py`, các model/result của reconciliation, `frontend-next/`, `src/analysis/`, `src/api/insights.py`, `src/api/copilot.py` hoặc prompt/provider AI.

## Tiêu chí nghiệm thu

- Mỗi reject có bản ghi quarantine có thể truy vết tới file/unit/row/config.
- Record-level reject không dừng các record hợp lệ.
- Structural fatal không ghi dữ liệu sai và không thành completed.
- Có thể reprocess một nhóm quarantine bằng filter mà không đọc lại toàn bộ nguồn.
- Counters đầu vào, success, rejected, duplicate và partial được đối chiếu được.
- EDA sinh được profile reproducible cho ít nhất một file chuẩn và các fixture có schema thay đổi.
- Quality profile phân biệt được `PASS`, `REVIEW`, `FAIL`; các row bị reject có thể truy vết sang quarantine.
- Các phép tính amount không dùng float làm authority tài chính; profile giữ precision phù hợp với `Decimal`/đơn vị tiền tệ.
- EDA không thay đổi kết quả reconciliation hoặc bypass mapping approval.
