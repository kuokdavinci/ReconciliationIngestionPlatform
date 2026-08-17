# Sprint 3 — EDA, Data Quality và Quarantine

## 1. Mục tiêu

Sprint 3 xây dựng một quality flow có thể giải thích và truy vết cho ingestion:

```text
raw file → EDA/profile → quality gate
                         ├─ PASS → normalize/validate/persist
                         ├─ REVIEW → mapping/operator review
                         └─ FAIL → batch failure hoặc quarantine
```

Kết quả bắt buộc:

- Dùng EDA để hiểu dữ liệu giao dịch và biến các finding có bằng chứng thành quality rule deterministic.
- Phân biệt lỗi ở cấp batch/file với lỗi ở cấp record.
- Lưu mọi record bị reject vào quarantine cùng lineage, reason và config version.
- Reprocess được một record hoặc một nhóm quarantine có kiểm soát mà không phải đọc lại toàn bộ source.
- Chứng minh behavior bằng profile reproducible, counters, integration tests và demo scenarios.

Sprint này không xây AML/fraud model, không sửa logic reconciliation và không đưa AI mapping vào quality gate.

## 2. Phạm vi và ranh giới

### Trong phạm vi

- EDA/profile cho các fixture CSV, Excel và JSON hiện có.
- Canonical data-quality contract sau mapping/normalization.
- Quality gate với quyết định `PASS`, `REVIEW` hoặc `FAIL`.
- Taxonomy và lifecycle của `VALID`, `DUPLICATE`, `RECORD_REJECTED` và `BATCH_FATAL`.
- Quarantine persistence, query, retry và reprocess có audit history.
- Counters cho input, success, rejected, duplicate và partial batch.
- Test deterministic, integration test và demo evidence.

### Ngoài phạm vi

- Không sửa `src/reconciliation/` hoặc các model/result của reconciliation.
- Không sửa `frontend-next/`.
- Không mở rộng `src/analysis/`, insights, copilot hoặc prompt/provider AI.
- Không triển khai ML anomaly detection trong Sprint 3.
- Không tự động thay thế mapping approval bằng EDA hoặc quality gate.
- Không tự động reject chỉ vì một statistical outlier nếu chưa có business threshold được phê duyệt.
- UI quality dashboard và Airflow orchestration là follow-up, chỉ thực hiện sau khi profile contract và quality rules ổn định.

## 3. Hiện trạng và nguyên tắc tích hợp

Hiện repository đã có các ranh giới cần tái sử dụng:

- `src/normalizer/normalizer.py` và `src/validators/validator.py` đã trả về lỗi có `field`, `reason`, `row` và `trace`.
- `IngestionPipeline` hiện xử lý lỗi row bằng cách gom vào list/log; lỗi chưa được persist thành quarantine record.
- Row-level error có thể tiếp tục các record khác, nhưng lỗi reader, config, schema hoặc persistence phải làm file/batch `FAILED`.
- `ProcessingStats` mới có `total/success/failed`, chưa phân biệt rejected, duplicate, quarantined và input reconciliation.

Nguyên tắc của Sprint 3:

1. Không rewrite normalizer hoặc validator từ đầu; chỉ chuẩn hóa contract và bổ sung behavior còn thiếu.
2. Downstream không được parse free-text error message để quyết định action.
3. EDA dùng để phát hiện drift/chất lượng và đề xuất rule; runtime authority vẫn thuộc về mapping approval, normalizer và validator.
4. Amount trong profile không dùng float làm authority tài chính; giữ precision phù hợp với `Decimal` hoặc đơn vị tiền tệ.

## 4. Workstream A — EDA và quality profile

### 4.1. Dataset và mục đích

- Sử dụng **IBM AML — Low Illicit (LI)** làm external financial-transaction
  dataset cho EDA.
- Mục đích là thực hành EDA và Data Quality profiling, không xây AML/fraud
  model.
- Dataset không cần khớp hoàn toàn với partner schema production. Chỉ đưa
  finding vào runtime khi có lý do business hoặc engineering rõ ràng.

### 4.1.1. Frozen ingestion baseline

Sprint 3 sử dụng hai prefix deterministic của cùng file `LI-Small_Trans.csv`
để đo regression ở ingestion boundary trước khi thêm quality rules:

| Benchmark | Input | Persisted | Duplicate | Failed | Ingestion time |
|---:|---:|---:|---:|---:|---:|
| Sprint 3 IBM AML-LI 10k | 10,000 | 7,554 | 2,446 | 0 | 1.161 s |
| Sprint 3 IBM AML-LI 100k | 100,000 | 74,999 | 25,001 | 0 | 12.808 s |
| Phase 1 Hybrid PostgreSQL 100k | 99,997 | n/a | n/a | n/a | **12.555 s** |

Hai case dùng cùng cấu hình `batch_size=20,000`, `write_workers=1`,
`ordered_insert=false`, `fast_mode=false` và chưa bật quality rules. Đây là
baseline của `IngestionPipeline.process_file`, không phải E2E benchmark; nó
không bao gồm reconciliation, API/Airflow orchestration, service startup,
quarantine reprocess hoặc dataset preparation.

`From Account` hiện được dùng làm ingestion key để freeze behavior của hệ
thống hiện tại, vì vậy duplicate count là một finding của baseline, chưa phải
quality-rule result. Profile, checksum và toàn bộ benchmark evidence nằm trong
file baseline canonical duy nhất:
[`baseline.md`](../../data/eda/ibm_aml_li/profiles/baseline.md).

Phase 1 là historical ZALOPAY reference. Case IBM AML-LI 100k hiện tại chậm
hơn `0.253 s` khoảng `2.0%`, chưa cho thấy material ingestion regression sau
Sprint 1–2. Đây là đối chiếu định hướng vì dataset, mapping, duplicate
distribution và worker configuration khác nhau. Mốc Phase 1 `4.577 s` thuộc
reconciliation, không thuộc ingestion baseline này.

Attempt 100k với cấu hình mặc định `write_workers=2` bị PostgreSQL deadlock ở
40,000 rows do các ingestion key trùng giữa nhiều batch ghi đồng thời. Sprint
3 tạm freeze benchmark với một worker; concurrent conflict handling là một
finding riêng cần benchmark sau khi có fix.

### 4.2. Deliverable

Tạo một notebook hoặc script reproducible, ví dụ:

```text
scripts/eda/partner_quality_profile.py
# hoặc
notebooks/eda_partner_quality.ipynb
```

EDA phải chạy được bằng Pandas/NumPy trên dataset được chọn, ít nhất một file chuẩn và các fixture có schema thay đổi. Exploratory analysis nằm ngoài production runtime và kết thúc bằng phần `Findings → Pipeline Implications`.

### 4.3. Canonical profile

Sau khi áp dụng mapping tương ứng, profile phải quy về các field canonical:

```text
transaction_id, trace, amount, status, transaction_date, currency
```

Profile tối thiểu gồm:

- shape, columns, head, info, dtypes và phân loại numerical/categorical/datetime/identifier;
- row count và column count;
- data type, nullable behavior và unique count;
- missing count/rate theo field;
- exact duplicate và duplicate theo business identity;
- amount min, median, mean, quartiles, P95, P99, max và IQR;
- date range, transactions/day hoặc transactions/hour;
- status/currency/type distribution và rare category;
- schema drift: missing/new column, mapping bắt buộc bị thiếu, type mismatch và thay đổi đáng kể so với baseline.

### 4.4. Quy tắc diễn giải EDA

- Required field bị thiếu có thể tạo `RECORD_REJECTED`; optional field thiếu có thể là `WARNING` hoặc accepted tùy contract.
- Exact duplicate là idempotency outcome.
- Duplicate cùng identity nhưng payload khác nhau là candidate để reject và quarantine vì có khả năng conflicting duplicate.
- Amount right-skew hoặc extreme value chỉ tạo cảnh báo/review nếu chưa có business threshold.
- IQR và percentile là phương pháp ưu tiên; chỉ dùng z-score khi giả định về distribution phù hợp.
- Categorical value xuất hiện trong public dataset không tự động trở thành production domain hard-code.
- Temporal anomaly chủ yếu phục vụ monitoring/review; timestamp invalid có thể reject nếu vi phạm deterministic business rule.

### 4.5. Quality profile output

Profile phải sinh output machine-readable và report giải thích được, tối thiểu bao gồm:

```text
quality_profile
├── input_rows
├── valid_rows
├── rejected_rows
├── duplicate_rows
├── quality_score
├── rule_results[]
└── decision: PASS | REVIEW | FAIL
```

Mỗi finding phải nối được từ evidence sang pipeline implication, ví dụ:

| Finding | Evidence | Pipeline implication |
|---|---|---|
| Amount right-skewed | Median thấp hơn mean đáng kể | Không dùng mean làm hard threshold |
| Extreme amount tồn tại | P99 thấp hơn max rất xa | Statistical outlier mặc định là `WARNING/REVIEW` |
| Required field có missing | Null-rate profiling | Required-field rule và `RECORD_REJECTED` |
| Categorical domain hữu hạn | Frequency/profile | Config-driven domain validation |
| Duplicate identity có payload khác | So sánh theo duplicate key | Conflicting duplicate → quarantine candidate |
| Volume thay đổi theo thời gian | Daily/hourly profile | Monitoring baseline, không auto-reject |

## 5. Workstream B — Data Quality Contract và Quality Gate

### 5.1. Rule result deterministic

Quality rule phải trả về object có cấu trúc, không chỉ free-text:

```text
QualityRuleResult
├── rule_code
├── field
├── severity
├── phase
├── result
├── actual
├── expected
└── message
```

Rule code ban đầu:

- `REQ_AMOUNT`
- `INVALID_AMOUNT`
- `REQ_CURRENCY`
- `UNSUPPORTED_CURRENCY`
- `INVALID_TIMESTAMP`
- `CONFLICTING_DUPLICATE`
- `SCHEMA_MISSING_COLUMN`
- `SCHEMA_TYPE_MISMATCH`
- `AMOUNT_OUTLIER`

`WARNING` là severity của một rule bất thường nhưng chưa đủ căn cứ để reject. Nó không được tự động biến thành record invalid.

### 5.2. Quality gate

Quality gate nhận quality profile và rule results, sau đó đưa ra quyết định ở cấp file/batch:

| Decision | Ý nghĩa | Action |
|---|---|---|
| `PASS` | Cấu trúc và chất lượng trong contract | Tiếp tục normalize/validate/persist |
| `REVIEW` | Có drift/cảnh báo cần operator hoặc mapping review | Dừng hoặc chờ approval theo flow hiện có |
| `FAIL` | Không đáp ứng cấu trúc/config bắt buộc | `BATCH_FATAL`, không ghi dữ liệu sai |

Quality gate không bypass mapping approval và không thay thế authority của normalizer/validator.

### 5.3. Outcome processing

Decision của quality profile khác với outcome của từng record:

| Outcome | Ý nghĩa | Action |
|---|---|---|
| `VALID` | Record qua deterministic rules | Persist và tiếp tục reconciliation |
| `DUPLICATE` | Equivalent record đã tồn tại | Skip/count theo idempotency contract |
| `RECORD_REJECTED` | Chỉ record này không hợp lệ | Quarantine và tiếp tục record hợp lệ |
| `BATCH_FATAL` | Reader/schema/config/persistence failure | Dừng batch, không đánh dấu completed |

Một batch có thể chứa `VALID`, `DUPLICATE` và `RECORD_REJECTED`; `BATCH_FATAL` là lỗi structural hoặc system-level, không phải lỗi dữ liệu của một row.

## 6. Workstream C — Hoàn thiện validation contract

Giữ lại validation hiện có cho:

- required fields;
- amount;
- date/timestamp integrity;
- status và domain constraint.

Chuẩn hóa `ValidationError` với tối thiểu:

```text
code, phase, severity, field, row, trace, reason
```

Normalizer và validator phải trả `code/phase/severity` ổn định để pipeline có thể quyết định `RECORD_REJECTED` hay `BATCH_FATAL` mà không phụ thuộc vào text.

## 7. Workstream D — Quarantine persistence và lifecycle

### 7.1. Record contract

Tạo collection Mongo `ingestion_quarantine_record` cho dữ liệu lỗi linh hoạt và audit-friendly. Mỗi record phải giữ:

- `quarantine_id`;
- source file/unit và source location;
- partner và reconciliation date;
- row number;
- sanitized raw row;
- error `code`, `phase`, `severity` và reason;
- mapping/config version;
- attempt count và resolution metadata;
- created/updated/reprocessed timestamps.

Raw row phải được sanitize trước khi lưu; không đưa secret hoặc credential vào quarantine.

### 7.2. Lifecycle

```text
PENDING → REPROCESSING → RESOLVED
                       └→ REJECTED
```

- `PENDING`: record chờ operator sửa mapping/data hoặc chờ retry.
- `REPROCESSING`: đang được xử lý bởi một reprocess attempt.
- `RESOLVED`: reprocess thành công và record đã persist theo contract mới.
- `REJECTED`: attempt vẫn không hợp lệ; giữ reason mới và lịch sử các attempt trước.

Không xóa historical quarantine record khi reprocess. Nếu quarantine write thất bại, file/batch không được đánh dấu completed; phải giữ trạng thái failed để tránh mất record lỗi.

Quarantine write phải có batch policy và retry/error policy rõ ràng, đồng thời phải xử lý được partial batch mà không làm mất lineage của row đã reject.

## 8. Workstream E — Query và reprocess

Backend chỉ cần API vận hành tối thiểu trong Sprint 3; không làm frontend.

```http
GET /api/v1/quarantine
POST /api/v1/quarantine/reprocess
```

Filter tối thiểu:

- `partner`;
- `status`;
- `phase`;
- `error_code`;
- `source_file_id`;
- `source_unit_key`;
- date range.

`POST /api/v1/quarantine/reprocess` phải nhận `quarantine_id` hoặc query filter, cho phép dùng mapping version mới và tạo attempt mới:

```text
PENDING
   ↓
operator sửa mapping/data
   ↓
REPROCESSING
   ├─ valid   → persist → RESOLVED
   └─ invalid → REJECTED + attempt_count increment
```

Reprocess selected record/group thay vì rerun toàn bộ source nếu có thể. Mỗi attempt phải có timestamp, mapping/config version, actor/trigger và resolution reason để phục vụ audit.

## 9. Workstream F — Counters và batch semantics

Mở rộng stats để có thể đối chiếu:

```text
input = success + rejected + duplicate
```

Khi batch đang partial, các record chưa hoàn tất phải được biểu diễn riêng; không gộp chúng vào `success` hoặc âm thầm bỏ qua. Tối thiểu cần phân biệt:

- `input_rows`;
- `success_count`;
- `rejected_count`;
- `duplicate_count`;
- `quarantined_count`;
- partial/failed state.

`RECORD_REJECTED` không dừng các record hợp lệ. `BATCH_FATAL` không được đánh completed và không được ghi dữ liệu đã biết là sai cấu trúc.

## 10. File dự kiến modified

- `src/domain/ingestion/quarantine.py` và `src/infrastructure/ingestion/quarantine_repository.py` — model, enum, lifecycle và repository.
- `src/infrastructure/persistence/mongo_indexes.py` — index theo file/unit/status/partner và index phục vụ reprocess.
- `src/core/types.py` — mở rộng `ValidationError` và `ProcessingStats`.
- `src/normalizer/normalizer.py` — error code/phase nhất quán cho normalize.
- `src/validators/validator.py` — severity/code và phân biệt validation với duplicate.
- `src/pipeline/ingestion_pipeline.py` — fatal-vs-record, quarantine batch và counters.
- `scripts/eda/partner_quality_profile.py` hoặc `notebooks/eda_partner_quality.ipynb` — profile fixture và report.
- `src/quality/` — quality rules deterministic dùng chung sau khi thử nghiệm trong EDA; không trộn với AI insights.
- `src/domain/ingestion/models.py` và `src/infrastructure/ingestion/file_repository.py` — rejected/duplicate/quarantine counts và batch state.
- `src/api/automation.py` hoặc router ingestion mới — API vận hành reprocess.
- `tests/test_validator.py`, `tests/test_normalizer.py`, `tests/test_ingestion_integration.py`, `tests/test_models.py` — validation, quarantine, fatal structure, partial batch và reprocess.
- `tests/test_data_quality_profile.py` — profile, schema drift, missing/duplicate, outlier flag và quality decision.

Tên file ở trên là boundary dự kiến; nếu repository đã có abstraction tương đương thì tái sử dụng abstraction đó thay vì tạo bản sao.

## 11. Tiêu chí nghiệm thu

- Mỗi `RECORD_REJECTED` có quarantine record truy vết được tới file/unit/row, partner, reason và config version.
- Record-level reject không dừng các record hợp lệ.
- Structural `BATCH_FATAL` không ghi dữ liệu sai và không thành completed.
- Quarantine write failure không làm mất record lỗi và giữ batch ở trạng thái failed/retryable phù hợp.
- Có thể query và reprocess một nhóm quarantine bằng filter mà không đọc lại toàn bộ source.
- Reprocess giữ attempt history; thành công chuyển `RESOLVED`, thất bại giữ reason mới và tăng `attempt_count`.
- Counters input, success, rejected, duplicate, quarantined và partial có thể đối chiếu được.
- EDA sinh profile reproducible cho ít nhất một file chuẩn và các fixture có schema thay đổi.
- Quality profile phân biệt được `PASS`, `REVIEW`, `FAIL`; row bị reject nối được sang quarantine.
- Amount profile giữ precision phù hợp với `Decimal`/currency unit và không dùng float làm authority tài chính.
- EDA không thay đổi kết quả reconciliation và không bypass mapping approval.
- Test chứng minh duplicate là idempotency outcome, conflicting duplicate là quarantine candidate, còn statistical outlier mặc định là warning/review.
