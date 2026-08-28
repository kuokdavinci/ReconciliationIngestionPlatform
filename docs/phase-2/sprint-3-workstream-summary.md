# Sprint 3 — Workstream A Decision Matrix

Canonical navigation: [Sprint 3 index](sprint-3-index.md).

Workstream A hoàn thành phần EDA/profile, provenance, controlled mutations,
frozen ingestion baseline và coverage handoff. Tài liệu này chỉ giữ các
quyết định và rule cần đối chiếu cùng EDA notebook; không phải runtime
quality-gate approval.

> Đây là tài liệu handoff lịch sử của Workstream A. Mapping và timestamp
> contract hiện tại do Workstream C sở hữu; xem
> [`sprint-3-workstream-c-normalization-validation.md`](sprint-3-workstream-c-normalization-validation.md)
> cho behavior runtime và evidence mới nhất.

## Dataset evidence

| Item | Kết quả |
|---|---|
| Dataset | Fraud Detection Dataset, 1.000.000 rows, 17 columns |
| Profile | Version `3`; SHA-256 `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6` |
| Deterministic result | `valid=1,000,000`, `rejected=0`, `duplicate=0`, decision `PASS` |
| Test evidence | 26 profile/mutation tests documented; profile + benchmark suite: 30 passed |

## EDA → runtime → implementation decision

| Rule / candidate | EDA evidence | Hệ thống thực tế | Quyết định triển khai | Status / owner |
|---|---|---|---|---|
| `SCHEMA_REQUIRED_COLUMNS`, `REQ_TRANSACTION_ID`, `REQ_AMOUNT`, `REQ_CURRENCY` | Required columns/values có trong clean dataset; mutation tests có coverage | Mapping/normalizer/validator đã có required-field boundary | `FATAL` ở file level cho required schema; `RECORD` reject/quarantine cho required value; không sinh random identity | `COVERED` — B/C maintain |
| `INVALID_AMOUNT` | Decimal parse hợp lệ; không có negative amount; zero được giữ hợp lệ | Validator reject parse fail/negative amount | `RECORD` reject/quarantine; dùng `Decimal` làm authority | `COVERED` — C maintain |
| `MALFORMED_ROW` | Profile đếm malformed/blank rows | Reader/normalizer trả row errors; D lưu routed reject với row context | Giữ row index/reason; reject/quarantine theo C/D contract | `COVERED` — C/D |
| `SCHEMA_DRIFT` | Profile phát hiện missing optional/unexpected columns | File quality gate phân biệt append-only warning với breaking/fatal drift | Required/breaking drift → `FATAL`; append-only drift → `WARNING/REVIEW` | `COVERED` — B/C |
| `INVALID_TIMESTAMP`, `TIMESTAMP_TIMEZONE_REQUIRED` | 1M timestamp parse được, có timezone và second precision | Workstream C map `timestamp → transDate`, normalize ISO/offset values và giữ structured error | Parse fail → `RECORD` reject; không advance source unit khi quality hold | `COVERED` — C/D |
| `TIMESTAMP_PRECISION_DRIFT` | Dataset có second precision ổn định | Chưa có partner precision contract | Chỉ `WARNING`/monitoring, không reject tự động | `DO_NOT_PROMOTE` — F/partner |
| `UNIQUE_TRANSACTION_ID` | `transaction_id` unique trong file này | Runtime idempotency dùng PostgreSQL `(identify, ingestion_key)`; scope khác EDA | Không tạo constraint chỉ từ file-local uniqueness; chốt canonical identity/reconciliation scope | `PARTIAL` — B |
| `EQUIVALENT_DUPLICATE` | Clean file không có duplicate tự nhiên; mutation test có | PostgreSQL conflict-safe insert và payload fingerprint classification đã có | `DUPLICATE` outcome, skip/persist idempotently, tăng counter, không fail batch | `COVERED` — B |
| `CONFLICTING_DUPLICATE` | Controlled mutation chứng minh cùng ID có thể khác payload | Bulk payload comparison, fingerprint evidence, quarantine và source-unit hold đã có | Compare payload; conflict → `REVIEW`/quarantine, giữ lineage/reason | `COVERED` — B/D |
| `AMOUNT_DESCRIPTIVE_OVERFLOW` | IQR flag 87.583 rows, 8.7583%; false-positive risk cao | Không dùng IQR làm quality decision | Chỉ observation/monitoring; chỉ promote khi có business threshold | `DO_NOT_PROMOTE` — partner |
| `FRAUD_SEMANTICS` | `fraud_type` có conditional meaning với `is_fraud` | Giữ trong `extra`; không phải canonical ingestion field | Không đưa vào quality gate hiện tại | `DO_NOT_PROMOTE` — partner/domain |
| `COORDINATE_SEMANTICS`, `CARD_CUSTOMER_CONSISTENCY`, `MERCHANT_LOCATION_CONSISTENCY` | Có relationship/range findings trong EDA | Chưa có business invariant/CRS contract | Monitoring/review candidate; không auto-reject | `DO_NOT_PROMOTE` — partner |
| `TEMPORAL_VOLUME` | Chỉ là descriptive time baseline | Chưa có expected calendar/volume contract | Chỉ dùng cho observability baseline | `DO_NOT_PROMOTE` — F/partner |

## Quyết định kỹ thuật chính

- Profile engine generic; dataset-specific schema nằm ở adapter/config, không
  biến notebook thành runtime dependency.
- Raw dataset giữ local/ignored; track manifest, checksum và profile outputs.
- Required fields, Decimal amount và negative-amount policy là deterministic
  rules được phép promote.
- EDA uniqueness là file-local; không thay thế runtime idempotency hoặc
  reconciliation identity.
- Equivalent duplicate và conflicting duplicate phải có outcome khác nhau;
  `ON CONFLICT DO NOTHING` không đủ để chứng minh payload conflict đã xử lý.
- Statistical, fraud và semantic findings không được auto-reject khi chưa có
  partner/business contract.
- Notebook Kaggle giữ nguyên; profile/review documents là evidence repository.

## Frozen ingestion baseline

Boundary: `IngestionPipeline.process_file()`; không tính reconciliation,
startup hoặc prefix preparation.

| Prefix | Persisted | Failed | Duplicate | Thời gian | Throughput |
|---:|---:|---:|---:|---:|---:|
| 10.000 | 10.000 | 0 | 0 | 1.122s | 8.910,8 rows/s |
| 100.000 | 100.000 | 0 | 0 | 9.496s | 10.530,8 rows/s |
| 1.000.000 | 1.000.000 | 0 | 0 | 102.439s | 9.762,0 rows/s |

Mapping v2 chính: `transaction_id → id`, `amount → Decimal amount`,
`currency → currency`, `timestamp → transDate`, `status ← SUCCESS`;
`fraud_type` không map canonical. Full-dataset v2 evidence nằm trong
[Workstream C baseline](sprint-3-workstream-c-baseline.md).

## Handoff

| Workstream | Phần tiếp nhận |
|---|---|
| B — Quality contract/gate | Identity scope, schema severity, timestamp contract, duplicate payload comparison |
| C — Normalization/validation | Timezone-aware `transDate`, structured validation errors, required/amount rules; full-dataset v2 evidence pending |
| D — Quarantine lifecycle | Conflicting duplicate, lineage, reason, reprocess evidence |
| F — Observability/acceptance | Precision, temporal volume, monitoring baseline |

Chi tiết: [Sprint 3 index](./sprint-3-index.md),
[Sprint 3 data-quality](./sprint-3-data-quality.md),
[EDA review](./sprint-3-eda-review.md),
[quality profile](../../data/eda/fraud_detection/profiles/quality_profile.md),
[Workstream C baseline](./sprint-3-workstream-c-baseline.md).
