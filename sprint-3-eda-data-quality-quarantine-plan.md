# Sprint 3 - EDA, Data Quality & Quarantine

**Dự án:** Reconciliation Ingestion Platform
**Mục tiêu Sprint:** `EDA & Profiling → Data Quality Contract → Quality Gate → Quarantine & Reprocess → Test/Demo`

---

## 1. Mục tiêu Sprint 3

- Sử dụng EDA để hiểu đặc điểm dữ liệu giao dịch tài chính và rút ra các giả định Data Quality dựa trên bằng chứng.
- Chuyển các finding phù hợp thành các validation rule và quality rule deterministic trong ingestion pipeline.
- Phân loại rõ outcome thành: `VALID`, `WARNING`, `DUPLICATE`, `REJECT`, `BATCH_FATAL`.
- Lưu các record bị reject vào quarantine với đầy đủ lineage và hỗ trợ reprocess có kiểm soát.
- Chứng minh end-to-end behavior bằng test reproducible, counters và các scenario demo với mentor.

```text
Dataset → EDA/Profile → Findings → Data Quality Rules

Partner Source → Mapping/Normalize → Validate/Quality Gate
    ├─ VALID       → Persist → Reconciliation
    ├─ WARNING     → Persist/flag
    ├─ DUPLICATE   → Skip/count
    ├─ REJECT      → Quarantine → Review/Fix → Reprocess
    └─ BATCH_FATAL → Stop batch
```

---

## 2. Hiện trạng repository

- Row-level processing đã được tách khỏi persistence thông qua `RowProcessor` và `RowBatchCoordinator`.
- `Validator` đã kiểm tra required fields, amount, date integrity và status; đồng thời collect nhiều lỗi thay vì fail-fast.
- Quarantine model và batch persistence đã tồn tại. Sprint 3 sẽ tập trung **hoàn thiện lifecycle, taxonomy, query/reprocess và failure semantics**, không xây lại quarantine từ đầu.
- `fast_mode` hiện đang bypass `Validator`, vì vậy cần xử lý rõ validation parity giữa fast path và normal path.

---

# 3. Workstream A - EDA trên IBM AML LI Dataset

## 3.1. Lựa chọn dataset và mục đích

- Sử dụng **IBM AML - Low Illicit (LI)** làm external financial-transaction dataset.
- Mục đích: thực hành EDA và Data Quality profiling trên transaction data, **không xây AML/Fraud model**.
- Dataset không bắt buộc phải khớp hoàn toàn với partner schema production.
- Chỉ đưa các finding vào hệ thống khi chúng hợp lý về business hoặc engineering.

## 3.2. Deliverable notebook

```text
notebooks/
└── ibm_aml_transaction_eda.ipynb
```

- Giữ exploratory analysis tách khỏi production runtime.
- Notebook phải kết thúc bằng phần **Findings → Pipeline Implications**.

## 3.3. Nội dung EDA

### A. Dataset understanding

- Kiểm tra `shape`, `columns`, `head()`, `info()`, `dtypes`.
- Phân loại các field:
  - numerical
  - categorical
  - datetime
  - identifier

### B. Schema profiling

- Kiểm tra:
  - column names
  - data types
  - nullable behavior
  - unique count
  - cardinality
- Xác định các candidate cho:
  - required-column rule
  - type rule
  - mapping constraint

### C. Missing-value analysis

- Tính null count và null percentage theo field.
- Phân biệt:
  - required field missing → `REJECT`
  - optional field missing → `ACCEPT/WARNING`
- Không coi mọi `null` là invalid data.

### D. Duplicate analysis

- Đo exact duplicate và duplicate theo business identity.
- Phân biệt:

```text
Exact duplicate:
TX01 / 100 USD
TX01 / 100 USD
→ idempotency outcome

Conflicting duplicate:
TX01 / 100 USD
TX01 / 150 USD
→ quarantine candidate
```

### E. Amount distribution

- Tính:
  - min
  - median
  - mean
  - quartiles
  - P95
  - P99
  - max
  - IQR
- Visualization:
  - histogram
  - boxplot
  - log-scale distribution nếu cần
- Statistical outlier mặc định chỉ là `WARNING/REVIEW` nếu chưa có business threshold xác định rõ invalid data.

### F. Categorical analysis

- Profile các field như:
  - currency
  - transaction type
  - payment format
- Kiểm tra rare/unexpected category.
- Không hard-code production rules chỉ dựa trên domain value xuất hiện trong public dataset.

### G. Temporal analysis

- Phân tích:
  - transactions/day
  - transactions/hour
  - amount theo thời gian
  - date range
  - weekday/weekend
  - volume spikes
- Temporal anomaly chủ yếu dùng cho monitoring/review.
- Invalid timestamp có thể `REJECT` nếu vi phạm business rule deterministic.

### H. Outlier / anomaly analysis

- Ưu tiên:
  - IQR
  - percentile
- Chỉ dùng z-score khi distribution assumption phù hợp.
- Không triển khai ML anomaly detection trong Sprint 3 nếu chưa thực sự cần.

## 3.4. EDA Findings Report

| Finding | Evidence | Pipeline implication |
|---|---|---|
| Amount bị right-skewed | Median thấp hơn mean đáng kể | Không dùng mean làm hard threshold |
| Extreme amount tồn tại | P99 thấp hơn max rất xa | Statistical outlier mặc định chỉ WARNING |
| Required field có thể bị thiếu | Null-rate profiling | Required-field validation / REJECT |
| Categorical domain hữu hạn | Currency/type frequency | Config-driven domain validation |
| Duplicate identity có thể khác payload | Duplicate-key comparison | Detect conflicting duplicate |
| Volume thay đổi theo thời gian | Hourly/daily profile | Monitoring baseline, không auto-reject |

---

# 4. Workstream B - Data Quality Contract

Tạo output deterministic cho quality rule thay vì phụ thuộc vào free-text error.

```text
QualityRuleResult
- rule_code
- field
- severity
- phase
- result
- actual
- expected
- message
```

### Rule code đề xuất

- `REQ_AMOUNT`
- `INVALID_AMOUNT`
- `REQ_CURRENCY`
- `UNSUPPORTED_CURRENCY`
- `INVALID_TIMESTAMP`
- `CONFLICTING_DUPLICATE`
- `SCHEMA_MISSING_COLUMN`
- `SCHEMA_TYPE_MISMATCH`
- `AMOUNT_OUTLIER`

---

# 5. Workstream C - Outcome Classification

| Outcome | Ý nghĩa | Action |
|---|---|---|
| `VALID` | Record thỏa deterministic rules | Persist và tiếp tục reconciliation |
| `WARNING` | Điều kiện bất thường/statistical nhưng chưa invalid | Persist/flag/metric, không auto-reject |
| `DUPLICATE` | Equivalent record đã tồn tại | Skip/count qua idempotency behavior |
| `REJECT` | Record-level invalid data | Persist quarantine và tiếp tục batch |
| `BATCH_FATAL` | Structural/config/read failure | Stop batch, không đánh dấu completed |

---

# 6. Workstream D - Hoàn thiện Validator

- Giữ lại các validation hiện có:
  - required fields
  - amount
  - date
  - status
- Không rewrite Validator từ đầu.
- Chuẩn hóa `ValidationError` gồm:
  - `code`
  - `phase`
  - `severity`
  - `field`
  - `row`
  - `trace`
  - `reason`
- Tránh downstream logic phải parse text trong error message để quyết định behavior.

---

# 7. Workstream E - Fast-Mode Validation Parity

`fast_mode` hiện skip `Validator`, nên cần biến đây thành contract rõ ràng.

### Hướng ưu tiên

- Chứng minh fast-path normalization/building enforce các invariant tương đương normal mode bằng parity tests.
- Nếu không chứng minh được parity:
  - chạy lightweight validation tương đương; hoặc
  - không cho phép fast mode trong production-quality ingestion.

```text
same invalid input
→ normal mode rejects
→ fast mode cũng phải rejects
```

---

# 8. Workstream F - Quarantine Hardening

- Giữ đầy đủ lineage:
  - source file/unit
  - partner
  - reconciliation date
  - row number
  - sanitized raw row
  - config version
  - timestamps
- Chuẩn hóa error code, phase và severity trong quarantine record.
- Lifecycle:

```text
PENDING → REPROCESSING → RESOLVED / REJECTED
```

- Định nghĩa rõ behavior khi:
  - quarantine write fail
  - partial batch
  - retry
- Không xóa historical quarantine record khi reprocess.

---

# 9. Workstream G - Quarantine Query & Reprocess

## 9.1. Query API

```http
GET /api/v1/quarantine
```

### Filter

- `partner`
- `status`
- `phase`
- `error_code`
- `source_file_id`
- `source_unit_key`
- `date range`

## 9.2. Reprocess lifecycle

```text
PENDING
   ↓
operator sửa mapping/data
   ↓
REPROCESSING
   ├─ valid   → persist → RESOLVED
   └─ invalid → REJECTED/PENDING + attempt_count increment
```

- Reprocess selected quarantine record/group thay vì rerun toàn bộ source nếu có thể.
- Giữ attempt history và resolution metadata để audit.

---

# 10. Workstream H - Dataset-Level Quality Profile & Gate

Tạo reusable quality layer:

```text
src/quality/
├── models.py
├── rules.py
├── profiler.py
└── gate.py
```

Quality profile có thể expose:

- input rows
- missing-required rate
- duplicate rate
- invalid-amount rate
- warnings
- rejected count
- decision

### Quality Gate

```text
PASS
REVIEW
FAIL
```

- `PASS`: schema compatible, không có fatal rule.
- `REVIEW`: drift/statistical anomaly cần xem xét nhưng chưa nên block pipeline.
- `FAIL`: structural/breaking issue khiến ingestion không an toàn.
- Rule-level decision là authority chính.
- Aggregate quality score nếu có chỉ dùng để tham khảo/reporting.

---

# 11. Workstream I - Schema Drift

So sánh expected schema với observed schema.

Detect:

- missing column
- unexpected column
- type change
- broken mapping dependency

Outcome:

```text
compatible drift → REVIEW
breaking drift   → FAIL
```

- Không auto-edit mapping.
- Không bypass mapping approval.
- Chỉ detect và route vấn đề tới đúng flow xử lý.

---

# 12. Workstream J - Counters & Invariants

Invariant chính:

```text
input_rows = persisted_rows + rejected_rows + duplicate_rows
```

- `warning_rows` có thể count riêng nhưng không được double-count nếu record đã persist.
- `quarantined_rows` là storage location của rejected record, không phải outcome cộng thêm vào invariant.

Ví dụ:

```text
input      = 100000
persisted  = 98500
rejected   = 500
duplicate  = 1000

100000 = 98500 + 500 + 1000
```

---

# 13. Test Plan

## 13.1. EDA/Profile tests

- profile row count
- missing rate
- duplicate rate
- amount percentiles
- schema drift
- outlier flag

## 13.2. Validator tests

- missing id
- missing currency
- missing amount
- negative amount
- invalid status
- invalid date
- multiple errors trên cùng một row

## 13.3. Quarantine tests

- invalid row → `PENDING`
- retain raw row
- retain source information
- retain row number
- retain error code
- retain config version

## 13.4. Pipeline integration tests

```text
100 rows
├─ 95 valid
├─ 3 invalid
└─ 2 duplicate

Expected:
95 persisted
3 quarantined
2 duplicate
batch vẫn tiếp tục
```

## 13.5. Reprocess tests

```text
invalid
→ quarantine
→ fix mapping/data
→ reprocess
→ persisted
→ RESOLVED
→ không tạo duplicate
```

---

# 14. Mentor Demo Scenarios

## Scenario 1 - Healthy dataset

```text
1,000 records
→ PASS
→ tất cả được xử lý
```

## Scenario 2 - Row-level problems

- Valid rows tiếp tục xử lý.
- Invalid rows đi vào quarantine.
- Duplicate được skip/count.
- Batch không fail vì record-level error.

## Scenario 3 - Structural failure

```text
Required column missing
→ Quality Gate = FAIL
→ batch bị block
→ không persist dữ liệu sai
```

## Scenario 4 - Reprocess

```text
Quarantine record
→ sửa mapping/data
→ reprocess
→ RESOLVED
```

---

# 15. Deliverables

- EDA notebook:
  - `notebooks/ibm_aml_transaction_eda.ipynb`
- EDA findings:
  - `docs/phase-2/sprint-3-eda-review.md`
- Data Quality rules/profile/gate:
  - `src/quality/`
- Hardened Validator và structured error taxonomy.
- Quarantine model/repository hardening.
- Quarantine query + reprocess backend API.
- Unit tests + integration tests.
- Sprint 3 final report:
  - `docs/phase-2/sprint-3-data-quality.md`

---

# 16. Ngoài phạm vi Sprint 3

- Fraud/AML classification.
- Machine Learning / Isolation Forest.
- Spark/Kafka/streaming redesign.
- AI-based validation.
- New frontend dashboard.
- Thay đổi reconciliation algorithm.
- Airflow redesign.
- Thêm Data Quality framework chỉ để làm đẹp tech stack.

---

# 17. Thứ tự triển khai đề xuất

1. **Freeze baseline**
   - Chạy test hiện tại.
   - Ghi nhận behavior hiện tại của Validator và Quarantine.

2. **Build IBM AML LI EDA notebook**
   - Hoàn thành schema/missing/duplicate/distribution/temporal/outlier profiling.

3. **EDA findings → rule matrix**
   - Phân loại rule thành `WARNING`, `REJECT`, `BATCH_FATAL`.

4. **Chuẩn hóa ValidationError**
   - code
   - phase
   - severity

5. **Đóng validation-parity gap của fast mode**

6. **Implement quality profile + deterministic gate**
   - `PASS`
   - `REVIEW`
   - `FAIL`

7. **Harden quarantine**
   - persistence
   - taxonomy
   - indexes
   - failure semantics

8. **Thêm quarantine query + reprocess lifecycle**

9. **Enforce counters và accounting invariants**

10. **Run integration/E2E scenarios**

11. **Benchmark khoảng 100k records**
   - Đo overhead do quality checks gây ra.

12. **Chuẩn bị mentor demo + final report**

---

# 18. Definition of Done

Sprint 3 được xem là hoàn thành khi:

- EDA reproducible và kết thúc bằng engineering implication có bằng chứng.
- Các rule có thể trace về business contract hoặc explicit EDA evidence, không dùng arbitrary threshold.
- Record-level invalid data không làm dừng valid records.
- Structural fatal error block batch an toàn.
- Mỗi reject trace được tới source file/unit/row/config và được persist vào quarantine.
- Có thể reprocess selected quarantine record/group mà không xóa history.
- Counters reconcile đúng giữa persisted, rejected và duplicate.
- Fast path và normal path có Data Quality guarantee tương đương.
- Mentor demo giải thích được:
  - Rule này đến từ đâu?
  - Vì sao statistical outlier không tự động invalid?
  - Rejected data được lưu ở đâu?
  - Recovery/reprocess hoạt động như thế nào?

---

# 19. Narrative trình bày với mentor

```text
IBM AML LI
   ↓
EDA
   ↓
Evidence / Findings
   ↓
Quality Rule Design

Partner Input
   ↓
Normalize
   ↓
Validate / Quality Gate
   ├─ valid            → persistence
   ├─ duplicate        → skip/count
   ├─ record invalid   → quarantine
   └─ structural fatal → block batch
                              ↓
                         fix mapping/data
                              ↓
                           reprocess
                              ↓
                           RESOLVED
```

**Trọng tâm Sprint 3:**

- **EDA** chứng minh khả năng hiểu và phân tích dữ liệu.
- **Deterministic Data Quality rules** chứng minh tư duy Data Engineering.
- **Quarantine + Reprocess** chứng minh reliability của production pipeline.
