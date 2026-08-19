# Fraud Detection Dataset — Ingestion quality profile

- Rows: 1,000,000 (valid shape: 1,000,000)
- Columns: 17
- SHA-256: `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6`
- Quality score: 100.0
- Decision: **PASS**

## Quality Summary

- Rejected rows: 0
- Duplicate rows: 0
- Conflicting primary-key groups: 0
- Missing cells: 998,510

## Timestamp

- Range: 2024-10-30T20:56:15+00:00 → 2025-10-30T20:54:55+00:00
- Rows with second precision: 1,000,000
- Rows with timezone: 1,000,000

## Amount observations

- min: 1.0
- q1: 9.86
- median: 20.09
- mean: 38.20037242
- q3: 40.93
- p95: 123.04
- p99: 294.1201
- max: 5000.0
- iqr: 31.07
- iqr_upper_bound: 87.535
- outlier_count: 87583
- outlier_rate: 0.087583

## Rule Results

| Rule | Severity | Result | Actual | Expected | Action |
|---|---|---|---|---|---|
| `SCHEMA_REQUIRED_COLUMNS` | FATAL | PASS | `{"duplicate_headers": [], "missing_required": []}` | `{"duplicate_headers": [], "missing_required": []}` | CONTINUE |
| `SCHEMA_DRIFT` | WARNING | PASS | `{"missing_optional": [], "unexpected": []}` | `{"missing_optional": [], "unexpected": []}` | CONTINUE |
| `MALFORMED_ROW` | RECORD | PASS | `0` | `0` | ACCEPT |
| `REQ_AMOUNT` | RECORD | PASS | `0` | `0` | ACCEPT |
| `REQ_CURRENCY` | RECORD | PASS | `0` | `0` | ACCEPT |
| `REQ_TIMESTAMP` | RECORD | PASS | `0` | `0` | ACCEPT |
| `REQ_TRANSACTION_ID` | RECORD | PASS | `0` | `0` | ACCEPT |
| `UNIQUE_TRANSACTION_ID` | RECORD | PASS | `0` | `0` | ACCEPT |
| `CONFLICTING_DUPLICATE` | RECORD | PASS | `0` | `0` | ACCEPT |
| `INVALID_TIMESTAMP` | RECORD | PASS | `0` | `0` | ACCEPT |
| `TIMESTAMP_TIMEZONE_REQUIRED` | RECORD | PASS | `0` | `0` | ACCEPT |
| `TIMESTAMP_PRECISION_DRIFT` | WARNING | PASS | `0` | `0` | ACCEPT |
| `INVALID_AMOUNT` | RECORD | PASS | `{"invalid_rows": 0, "negative_rows": 0}` | `{"invalid_rows": 0, "negative_rows": 0}` | ACCEPT |
| `AMOUNT_DESCRIPTIVE_OVERFLOW` | WARNING | PASS | `0` | `0` | ACCEPT |
| `INVALID_NUMERIC_VALUES` | WARNING | PASS | `{"by_field": {"merchant_latitude": 0, "merchant_longitude": 0}, "rows": 0}` | `0` | ACCEPT |

## Limitations

- Statistical observations are descriptive and do not establish business thresholds.
- Duplicate behavior is scoped to this file; persistence idempotency needs its own contract.
- Required fields, timestamp precision, and negative-amount policy require source-contract approval.
