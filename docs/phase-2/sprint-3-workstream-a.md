# Sprint 3 — Workstream A: EDA và baseline

**Trạng thái:** Đã hoàn tất EDA, profile, provenance, frozen baseline và
controlled mutations cho Fraud Detection Dataset.

## Phạm vi

| Hạng mục | Kết quả |
|---|---|
| Dataset | Fraud Detection Dataset, 1.000.000 rows, 17 columns |
| Profile | Version `3` |
| SHA-256 | `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6` |
| Kết quả deterministic | `valid=1,000,000`, `rejected=0`, `duplicate=0`, `PASS` |
| Test | 26 profile/mutation tests; profile + benchmark: 30 passed |
| Boundary | EDA/profile và ingestion baseline; không bao gồm reconciliation hay operator flow |

## Source-to-canonical baseline

| Source field | Canonical field | Quy tắc |
|---|---|---|
| `transaction_id` | `id` | Required |
| `timestamp` | `transDate` | Required `DATE`; v2 normalize ISO/offset về UTC |
| `amount` | `amount` | Required `DECIMAL`; zero hợp lệ |
| `currency` | `currency` | Required `STRING` |
| — | `status` | Gán `SUCCESS` trong benchmark |
| `customer_id`, `card_id`, `device_id`, `ip_address` | `extra.*` | Giữ làm context |
| `merchant_*`, `transaction_type`, `is_fraud` | `extra.*` | Giữ làm context |
| `fraud_type` | — | Không map vào canonical field |

`transaction_id` chỉ được chứng minh unique trong source file này. Runtime
idempotency dùng scope khác: `(identify, ingestion_key)`.

## EDA → runtime decision matrix

| Rule/candidate | Evidence | Quyết định |
|---|---|---|
| Required schema/field | 17-column shape ổn định; required fields có đủ | Schema thiếu/breaking → `FATAL`; required value thiếu → `REJECT`/quarantine |
| `INVALID_AMOUNT` | Parse bằng `Decimal`; không có amount âm | Không parse được hoặc âm → `REJECT`; zero hợp lệ |
| `MALFORMED_ROW` | Profile và mutation test có coverage | Giữ row context; `REJECT`/quarantine |
| `SCHEMA_DRIFT` | Có missing/unexpected column cases | Append-only → `WARNING`; breaking → `FATAL` |
| `INVALID_TIMESTAMP` | Dataset có timestamp hợp lệ, có timezone | Parse fail → `REJECT`; canonical contract do C duy trì |
| `EQUIVALENT_DUPLICATE` | Mutation test có case tương đương | Count/skip tại persistence; không quarantine |
| `CONFLICTING_DUPLICATE` | Mutation test chứng minh cùng ID khác payload | So sánh payload; quarantine và hold source unit |
| `UNIQUE_TRANSACTION_ID` | Unique trong file hiện tại | Không dùng làm global persistence constraint |
| Amount IQR/outlier | 87.583 rows bị flag, false-positive risk cao | Chỉ observation/monitoring |
| Fraud/entity/location/coordinate semantics | Có findings nhưng thiếu business contract | Không auto-reject |
| Temporal volume và timestamp precision | Chỉ là descriptive baseline | Monitoring/review candidate |

## Frozen ingestion baseline

Boundary là `IngestionPipeline.process_file()`; không tính reconciliation,
startup hoặc prefix preparation.

| Input rows | Persisted | Failed | Duplicate | Thời gian | Throughput |
|---:|---:|---:|---:|---:|---:|
| 10.000 | 10.000 | 0 | 0 | 1.122s | 8.910,8 rows/s |
| 100.000 | 100.000 | 0 | 0 | 9.496s | 10.530,8 rows/s |
| 1.000.000 | 1.000.000 | 0 | 0 | 102.439s | 9.762,0 rows/s |

## Implementation boundary

| Thành phần | Vai trò |
|---|---|
| `scripts/eda/quality_profile.py` | Generic profile engine |
| `scripts/eda/fraud_detection_dataset.py` | Dataset schema adapter |
| `scripts/eda/profile_fraud_dataset.py` | Dataset-specific profile runner |
| Kaggle notebook | Giữ nguyên; không phải runtime dependency |
