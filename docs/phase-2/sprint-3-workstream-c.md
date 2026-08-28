# Sprint 3 — Workstream C: Normalization và validation

**Trạng thái:** `Implemented`; full-dataset v2 evidence đã ghi nhận ngày
2026-08-26.

## Vấn đề và phạm vi

Đưa source `timestamp` về canonical `transDate`, giữ behavior normal/fast
nhất quán và trả structured validation error bounded.

| C xử lý | C không xử lý |
|---|---|
| Timestamp parsing, source mapping, required field, `Decimal`, canonical validation, persistence time mapping | Quality precedence, duplicate fingerprint, quarantine lifecycle, Airflow policy, PostgreSQL schema và reconciliation contract |

## Mapping và implementation

| Capability | Module | Core logic |
|---|---|---|
| Timestamp parsing | `src/normalizer/timestamps.py` | Strict ISO/offset và 4 legacy formats |
| Source mapping | `src/normalizer/normalizer.py` | `timestamp → transDate` |
| Canonical validation | `src/validators/validator.py` | Required/date/Decimal và structured violation |
| Persistence boundary | `src/infrastructure/partner_transaction/mappers.py` | Aware timestamp → UTC-naive cho PostgreSQL |
| Full-dataset runner | `scripts/benchmark_fraud_detection.py` | Chạy mapping v2 qua ingestion boundary thật |

| Source field | Canonical field | Contract |
|---|---|---|
| `transaction_id` | `id` | Required |
| `timestamp` | `transDate` | Required `DATE` |
| `amount` | `amount` | Required `DECIMAL`; zero hợp lệ; âm bị reject |
| `currency` | `currency` | Required `STRING` |
| — | `status` | Gán `SUCCESS` trong mapping v2 |

## Timestamp contract

| Input | Kết quả |
|---|---|
| `YYYY-MM-DDTHH:MM:SSZ` | Accept; aware `datetime`, normalize UTC |
| `YYYY-MM-DDTHH:MM:SS±HH:MM` | Accept; normalize về cùng UTC instant |
| ISO có 1–6 fractional digits và offset | Accept; giữ microsecond precision |
| `YYYY-MM-DD` | Accept; legacy naive `datetime` |
| `DD/MM/YYYY` | Accept; legacy naive `datetime` |
| `YYYY-MM-DD HH:MM:SS` | Accept; legacy naive `datetime` |
| `DD/MM/YYYY HH:MM:SS` | Accept; legacy naive `datetime` |
| Naive `datetime` object | Accept; không tự gán timezone |
| Empty, malformed, impossible date, naive ISO `T`, offset sai grammar | Reject deterministic |

## Validation và persistence

| Trường hợp | Rule/outcome |
|---|---|
| Timestamp source không parse được | `INVALID_TIMESTAMP / NORMALIZATION / ERROR / REJECT` |
| Canonical `transDate` không phải `datetime` | `INVALID_TIMESTAMP / VALIDATION / ERROR / REJECT` |
| Error evidence | Chỉ giữ `type`; không lộ raw timestamp |
| Review Runtime | Map structured `INVALID_TIMESTAMP` sang presentation code `INVALID_DATE`; không parse reason string |
| Normal/fast | Cùng canonical value, quality outcome và serialized evidence |
| PostgreSQL | Aware value normalize UTC rồi bỏ timezone đúng một lần; legacy naive giữ nguyên |
| Amount/required fields | Giữ contract hiện tại: Decimal string hợp lệ, zero hợp lệ, negative/non-finite/thiếu required bị reject |

Timestamp timezone absence không được nâng thành global rejection rule.
Amount IQR, fraud, entity/location/coordinate, temporal volume và timestamp
precision chỉ là monitoring/business candidates.

## Full-dataset v2 evidence

| Metadata | Giá trị |
|---|---|
| Boundary | `IngestionPipeline.process_file` |
| Dataset | `data/eda/fraud_detection/raw/Fraud Detection Dataset.csv` |
| Mapping | `sprint3-fraud-detection-v2` |
| SHA-256 | `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6` |
| Config | `batch_size=20,000`, `write_workers=1`, `ordered_insert=false`, `fast_mode=false` |
| Cleanup | Benchmark records và temporary mapping đã xóa |

| Input | Persisted | Failed/rejected | Duplicate | Quarantined | Quality | Outcome | Thời gian | Throughput |
|---:|---:|---:|---:|---:|---|---|---:|---:|
| 1,000,000 | 1,000,000 | 0 | 0 | 0 | `PASS` | `CONTINUE / INGESTED` | 125.588s | 7,962.5 rows/s |

| Stage | Thời gian |
|---|---:|
| Parse | 9.997s |
| Normalize/build | 25.169s |
| Validate | 3.225s |
| Database insert window | 123.833s |
| Post-insert update | 0.004s |
| Batch write operations | 52 |

Artifact: `data/eda/fraud_detection/profiles/benchmark_results_workstream_c.json`.

## Evidence và reproduce

| Kiểm tra | Kết quả |
|---|---|
| Focused C contract tests | `242 passed` ngày 2026-08-26 |
| Backend CI parity | `1,211 passed, 6 skipped` ngày 2026-08-25 |
| Ingestion CI parity | `57 passed` ngày 2026-08-25 |
| Generated 20-row smoke | `20/20`, zero failed/duplicate, `PASS / CONTINUE`, `INGESTED` |
| Full 1M v2 | Zero failed/duplicate/quarantined; `PASS / CONTINUE / INGESTED` |

```bash
uv run python scripts/benchmark_fraud_detection.py --full-only
```
