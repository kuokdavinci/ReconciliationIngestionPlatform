# Sprint 3 — Workstream B: Quality contract và gate

**Trạng thái:** `Implemented`.

## Vấn đề và phạm vi

Workstream B chuẩn hóa quality decision ở boundary giữa mapping/validation,
persistence và runtime orchestration. Kết quả phải deterministic, bounded và
không biến lỗi dữ liệu thành infrastructure retry.

Không thuộc B: Airflow scheduling/retry policy, schema migration, quarantine
resolution, statistical rule và fraud/business semantics.

## Rule registry

| Rule code | Phase | Outcome mặc định | Ý nghĩa |
|---|---|---|---|
| `REQUIRED_SCHEMA_PATH` | CONFIGURATION/FILE | `BATCH_FATAL` | Required canonical path chưa được map |
| `MISSING_REQUIRED_SOURCE_COLUMN` | FILE | `BATCH_FATAL` | Source thiếu column bắt buộc |
| `SCHEMA_CONFIG_DRIFT` | FILE | `WARNING`/`BATCH_FATAL` | Append-only drift có thể review; breaking drift là fatal |
| `SOURCE_STRUCTURE_UNREADABLE` | FILE | `BATCH_FATAL` | Không đọc được structure của source |
| `CONFIG_VALIDATION` | CONFIGURATION | `BATCH_FATAL` | Mapping config không hợp lệ |
| `MISSING_REQUIRED_FIELD` | NORMALIZATION/VALIDATION | `REJECT` | Row thiếu value bắt buộc |
| `MALFORMED_ROW` | NORMALIZATION | `REJECT` | Row không map được vào canonical shape |
| `INVALID_AMOUNT` | NORMALIZATION/VALIDATION | `REJECT` | Amount không phải `Decimal` hợp lệ |
| `NEGATIVE_AMOUNT` | VALIDATION | `REJECT` | Amount nhỏ hơn 0; zero hợp lệ |
| `INVALID_TIMESTAMP` | NORMALIZATION/VALIDATION | `REJECT` | Timestamp không đạt contract |
| `INVALID_STATUS` | VALIDATION | `REJECT` | Status ngoài canonical enum |
| `EQUIVALENT_DUPLICATE` | PERSISTENCE | `DUPLICATE` | Cùng key và cùng business payload |
| `CONFLICTING_DUPLICATE` | PERSISTENCE | `REVIEW` | Cùng key nhưng khác business payload |

## Core decision

| Quality decision | Runtime action | Kết quả |
|---|---|---|
| `PASS` | `CONTINUE` | Persist, reconcile, advance checkpoint, cleanup sau checkpoint commit |
| `REVIEW` do row reject/warning | `CONTINUE` | Row hợp lệ tiếp tục; row lỗi đi quarantine |
| `REVIEW` có `CONFLICTING_DUPLICATE` | `HOLD_FOR_REVIEW` | Không reconcile/advance/cleanup source unit |
| `FAIL` do file/config fatal | `FAIL` | Dừng trước row processing; không retry như infrastructure error |
| Infrastructure error | Existing retry policy | Giữ ngoài quality model |

Precedence: `BATCH_FATAL` → `FAIL`; nếu không có fatal nhưng có reject,
warning hoặc conflicting duplicate → `REVIEW`; chỉ `VALID` và equivalent
duplicate → `PASS`. `topRuleCodes` tối đa 10 phần tử.

## File gate và row gate

| Gate | Thời điểm | Kiểm tra | Kết quả |
|---|---|---|---|
| `FileQualityGate` | Sau config preparation, trước row iterator | Required path/column, mapping structure, structure drift | Fail thì không normalize hoặc persist row |
| Row gate | Trong normalizer + validator | Required field, shape, Decimal, timestamp, status | Row invalid → `REJECT`; row hợp lệ tiếp tục |

`FileQualityGate` chỉ inspect header (`sample_size=0`). Append-only column là
`WARNING`; breaking drift, config invalid và unreadable structure là
`BATCH_FATAL`. Gate không mutate mapping. Fast mode dùng cùng deterministic
rules với normal mode.

## Duplicate fingerprint

| Hạng mục | Contract |
|---|---|
| Kết quả persistence | Một `BatchWriteResult` và một `DuplicateDetail` cho mỗi key conflict |
| Fingerprint payload | `partner_id`, `partner_trace`, `partner_status`, normalized `Decimal amount`, `currency`, UTC `transDate`, canonical sorted metadata |
| Không đưa vào fingerprint | Database UUID, request ID, source file ID, timestamps persistence, persistence-only status |
| Equivalent duplicate | Count/skip; không tạo quarantine |
| Conflicting duplicate | Giữ incoming/existing fingerprint và row context để route quarantine |
| Query | Atomic insert/classification; chỉ một bulk payload lookup khi có conflict; không N+1 |

## Counter và runtime output

Với mỗi source unit đã hoàn tất:

```text
inputRows = persistedRows + rejectedRows + duplicateRows + persistenceFailedRows
```
`quarantinedRows` là storage count, không cộng vào invariant. Runtime giữ thêm
`equivalentDuplicateRows`, `conflictingDuplicateRows`, `warningRows` và
`persistenceFailedRows`.

Airflow/application output chỉ chứa summary:

```json
{
  "success": true,
  "outcome": "INGESTED",
  "qualityDecision": "REVIEW",
  "orchestrationAction": "HOLD_FOR_REVIEW",
  "qualityCounters": {
    "inputRows": 100,
    "persistedRows": 98,
    "rejectedRows": 1,
    "duplicateRows": 1
  },
  "topRuleCodes": ["CONFLICTING_DUPLICATE"]
}
```

Không đưa raw rows, full error list hoặc fingerprint vào XCom/output.

## Implementation map

| Module | Vai trò |
|---|---|
| `src/domain/ingestion/quality.py` | Rule, phase, severity, decision, violation, aggregation |
| `src/domain/partner_transaction/duplicates.py` | Fingerprint và duplicate evidence |
| `src/application/ingestion/quality_policy.py` | Map quality decision sang runtime action |
| `src/application/ingestion/contracts.py` | Serialize error và bounded result |
| `src/pipeline/quality_gate.py` | Chạy file gate đúng thứ tự |
| `src/infrastructure/partner_transaction/repository.py` | Atomic insert, conflict lookup, adapter result |

## Evidence

| Kiểm tra | Kết quả |
|---|---|
| 100-row integration accounting | `95 persisted + 3 rejected + 2 duplicates = 100` |
| Clean lookup/hash path | Zero existing-payload lookup/hash |
| Conflict path | Một bulk lookup/batch; không N+1 |
| Clean throughput, 1M rows | 8,955 vs 9,762 rows/s; regression `9.01%`, trong ngưỡng khoảng `10%` |
| Airflow bounded output | Kích thước không phụ thuộc số detailed errors |

Reproduce:

```bash
uv run python scripts/benchmark_quality_contract.py \
  --sizes 10000,100000,1000000 \
  --repeats 1 \
  --output /tmp/workstream-b-quality-benchmark.json
```
