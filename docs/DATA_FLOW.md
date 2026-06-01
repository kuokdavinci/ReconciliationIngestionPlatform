# Data Flow

## End-to-End Flow

Two main data flows exist in the system:

1. **Ingestion Flow** — Partner Excel files are parsed, normalized, validated, and persisted to `data_container`.
2. **Reconciliation Flow** — Ingestion output (`data_container`) is matched against internal system records (`internal_transaction`) to produce reconciliation reports (`reconciliation_result`).

---

## Ingestion Flow

```
User calls: pipeline.process_file(
    file_path="m4becomvsp_07072024_combine.xlsx",
    partner="MOMO",
    workflow_type="UPC",
    file_type=FileType.SETTLEMENT,
    reconciliation_date=datetime(2024, 7, 7),
)
```

### Step 1: File Hash & Duplicate Check

```
_compute_file_hash(file_path)
  → Reads file content in 8KB chunks (async via thread pool)
  → Returns SHA256 hex string

_recon_repo.find_by_file_hash(hash)
  → Query: {"fileHash": hash}
  → If found: return existing record + error (duplicate)
  → If not found: continue
```

### Step 2: Create Tracking Record

```
ReconciliationFile(
    partner="MOMO",
    file_name="m4becomvsp_07072024_combine.xlsx",
    file_hash="<sha256>",
    file_type=FileType.SETTLEMENT,
    reconciliation_date=datetime(2024, 7, 7),
    processing_status=ProcessingStatus.PROCESSING,
)
→ _recon_repo.create() → INSERT into reconciliation_file
→ Logger: emit_file_started(file_id, file_name, partner)
```

### Step 3: Load Mapping Configuration

```
_config_loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)
  → Cache check: "MOMO:UPC:SETTLEMENT:latest"
  → If hit: return cached config
  → If miss:
    → _repository.find_by_partner_and_type("MOMO", "UPC", "SETTLEMENT")
    → Query: {"partner": "MOMO", "workflowType": "UPC", "fileType": "SETTLEMENT"}
    → ConfigValidator.validate(config)
    → Cache put with TTL 300s
    → Return config
```

**Config structure returned:**
```json
{
  "partner": "MOMO",
  "workflowType": "UPC",
  "sheetName": "Sheet1",
  "startRow": 2,
  "fieldMappings": [
    { "path": "id", "column": 1, "type": "STRING", "required": true },
    { "path": "trace", "column": 10, "type": "STRING" },
    { "path": "amount", "column": 4, "type": "DECIMAL" },
    { "path": "currency", "constant": "VND", "type": "CONSTANT" },
    { "path": "status", "column": 17, "type": "MAPPING",
      "mapping": { "Thành công": "SUCCESS", "others": "FAILED" } },
    { "path": "transDate", "column": 7, "type": "DATE" }
  ]
}
```

### Step 4: Create Reader

```
ExcelStreamReader.from_mapping_config(file_path, config)
  → sheet_name=config.sheet_name ("Sheet1")
  → start_row=config.start_row (2)
  → skip_empty_rows=True
  → Opens workbook in read_only=True mode
```

### Step 5: Process Each Row

**Example Excel row (row 2, after header):**

| Col 1 | Col 2 | Col 3 | Col 4 | ... | Col 10 | ... | Col 17 |
|-------|-------|-------|-------|-----|--------|-----|--------|
| 61838642196 | 2024-07-05 | | 259200 | ... | 2407055711887385978413624 | ... | Thành công |

#### 5a: Normalize (row tuple passed directly)

```python
row_tuple = ("61838642196", "2024-07-05", None, 259200, ..., "2407055711887385978413624", ..., "Thành công")
normalizer = TransactionNormalizer(config.field_mappings)
norm_result = normalizer.normalize(row_tuple, row_number=2)
```

**Processing each FieldMapping (column numbers are 1-based, converted to 0-based index):**

| Mapping | Source (col#) | Conversion | Result |
|---------|---------------|------------|--------|
| `id` (STRING, col 1) | `row_tuple[0]` = `"61838642196"` | str() | `"61838642196"` |
| `trace` (STRING, col 10) | `row_tuple[9]` = `"2407055711887385978413624"` | str() | `"2407055711887385978413624"` |
| `amount` (DECIMAL, col 4) | `row_tuple[3]` = `259200` | Decimal(259200) | `Decimal('259200')` |
| `currency` (CONSTANT) | — | constant value | `"VND"` |
| `status` (MAPPING, col 17) | `row_tuple[16]` = `"Thành công"` | mapping lookup | `"SUCCESS"` |
| `transDate` (DATE, col 7) | `row_tuple[6]` = `"2024-07-05"` | strptime("%Y-%m-%d") | `datetime(2024, 7, 5)` |

**Result:**
```python
NormalizationResult(
    data={
        "id": "61838642196",
        "trace": "2407055711887385978413624",
        "amount": Decimal("259200"),
        "currency": "VND",
        "status": "SUCCESS",
        "transDate": datetime(2024, 7, 5),
    },
    errors=[],
)
```

#### 5c: Build CanonicalTransaction

```python
txn, build_errors = TransactionNormalizer.build_canonical(norm_result.data, [], row_number=2)
```

**Result:**
```python
CanonicalTransaction(
    id="61838642196",
    trace="2407055711887385978413624",
    amount=Decimal("259200"),
    currency="VND",
    status=TransactionStatus.SUCCESS,
    transDate=datetime(2024, 7, 5),
    extra={},
)
```

#### 5d: Validate (core validation only — file duplicate already checked at pipeline level)

```python
validator = Validator(data_container_repo=self._data_repo, reconciliation_file_repo=self._recon_repo)
validation_result = validator.validate(
    txn,
    row_number=2,
    trace="2407055711887385978413624",
)
```

**Checks performed:**
1. Required fields: id ✓, currency ✓
2. Decimal non-negative: 259200 >= 0 ✓
3. Date type: datetime ✓
4. Status enum: SUCCESS in TransactionStatus ✓

**Note:** File duplicate check is skipped here — already done at Step 1 of pipeline. Transaction duplicate check is also skipped in `validate()` (requires `validate_with_duplicates()` for that).

**Result:** `ValidationResult(is_valid=True, errors=[])`

#### 5e: Persist

```python
partner_data = PartnerData(
    _id="61838642196",
    trace="2407055711887385978413624",
    status="SUCCESS",
    amount=Decimal("259200"),
    currency="VND",
    transDate=datetime(2024, 7, 5),
    extra={},
)
data_container = DataContainer(
    identify="MOMO",
    workflow_type="UPC",
    reconciliation_date=datetime(2024, 7, 7),
    source_file_id=file_record.id,
    partner_data=partner_data,
)
batch_buffer.append(data_container)
```

**Logger:** `emit_row_success(file_id, row_number=2, trace="2407055711887385978413624")`

#### 5f: Batch Flush

```python
if len(batch_buffer) >= 100:  # batch_size
    inserted = await self._flush_batch(batch_buffer)
    success_rows += inserted  # Uses actual insert count
    batch_buffer = []
```

**MongoDB operation (via `_to_mongo()` for type conversion):**
```python
# Each DataContainer is converted:
# - UUID → string
# - Decimal → Decimal128
# - Nested partnerData preserved as object
collection.insert_many([
    doc._to_mongo()  # via DataContainerRepository.insert_many()
    for doc in batch_buffer
])
```

### Step 6: Final Flush & Stats Update

```python
# Flush remaining
if batch_buffer:
    inserted = await self._flush_batch(batch_buffer)
    success_rows += inserted

# Update stats
await _recon_repo.update_processing_stats(file_record.id, total_rows, success_rows, failed_rows)
await _recon_repo.update_status(file_record.id, ProcessingStatus.COMPLETED)

# Update in-memory record
file_record.processing_status = ProcessingStatus.COMPLETED
file_record.total_rows = total_rows
file_record.success_rows = success_rows
file_record.failed_rows = failed_rows
```

### Step 7: Return Result

```python
duration_ms = (time.monotonic() - start_time) * 1000
logger.emit_file_completed(file_id, total_rows, success_rows, failed_rows, duration_ms)

return IngestionResult(
    file_record=file_record,
    stats=ProcessingStats(total_rows=1000, success_rows=990, failed_rows=10),
    errors=[
        {"row": 142, "field": "amount", "reason": "invalid decimal value: 'abc'"},
        ...
    ],
)
```

## Error Scenarios

### Scenario 1: Invalid Row

**Input:** Row with `amount = "abc"`

```
normalize() → _convert_decimal("abc") → InvalidOperation
  → ValidationError(field="amount", reason="invalid decimal value: 'abc'")
  → norm_result.errors not empty
  → failed_rows += 1
  → errors.append({"row": 142, "field": "amount", "reason": "..."})
  → logger.emit_row_failed(file_id, 142, "", "invalid decimal value: 'abc'")
  → continue (next row)
```

### Scenario 2: Duplicate Transaction

**Input:** Row with trace already in data_container

```
validate_with_duplicates() → _check_transaction_duplicate()
  → Query returns existing document
  → ValidationError(field="duplicate", reason="transaction already exists")
  → failed_rows += 1
  → continue (next row)
```

### Scenario 3: Duplicate File

**Input:** Same file re-uploaded

```
_compute_file_hash() → SHA256 matches existing record
  → find_by_file_hash() returns existing
  → emit_file_failed("duplicate", "File already processed")
  → return IngestionResult(file_record=existing, errors=[{"field": "file_duplicate", ...}])
```

---

## Reconciliation Flow

Reconciliation is triggered via CLI:

```
uv run python run.py --reconcile 2024-07-07 --partner MOMO
```

### Step 1: Date Boundaries

```
reconciliation_date = datetime(2024, 7, 7, tzinfo=UTC)
start_of_day = datetime(2024, 7, 7, 0, 0, 0, tzinfo=UTC)
end_of_day   = datetime(2024, 7, 7, 23, 59, 59, 999999, tzinfo=UTC)
```

### Step 2: Fetch Partner Records (from Ingestion output)

```
DataContainerRepository.find_many({
    "identify": "MOMO",
    "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day}
})
```

**Query:** `data_container` collection with `idx_identify_date` index.

### Step 3: Fetch Internal Records (Mock DB)

```
InternalTransactionRepository.find_many({
    "partner": "MOMO",
    "transactionTime": {"$gte": start_of_day, "$lte": end_of_day}
})
```

**Query:** `internal_transaction` collection with `idx_internal_partner_txn_time` index.

### Step 4: Resolve Duplicate Internal Records

```python
internal_by_key: dict[str, InternalTransaction] = {}
for record in internal_records:
    key = record.partner_txn_id.strip()
    if key not in internal_by_key or record.updated_at > existing.updated_at:
        internal_by_key[key] = record
```

**Rule:** If multiple internal records share the same `partnerTxnId`, the one with the latest `updatedAt` wins. This handles correction scenarios where a previous record was updated/fixed.

### Step 5: Process Partner Records

For each `DataContainer` record:

**5a. Resolve partnerTxnId:**

```
_resolve_partner_txn_id(partner_record):
  1. Try partnerData.trace
  2. Try partnerData.extra.vspTransId
  3. Try partnerData.id
  4. If none → skip (log warning)
```

**5b. Look up by partnerTxnId:**

```python
internal_record = internal_by_key.get(partner_txn_id)
```

**5c. If found — compare and classify:**

```
Amounts: partner_amount == internal_amount?  (tolerance = 0)
Statuses: _normalize_status(partner_status) == _normalize_status(internal_status)?

Classification matrix:
  amounts_match && statuses_match   → MATCHED
  !amounts_match && !statuses_match → MULTIPLE_MISMATCH
  !amounts_match                    → AMOUNT_MISMATCH
  else                              → STATUS_MISMATCH
```

**Status normalization (`_normalize_status()`):**

| Input (case-insensitive) | Normalized |
|--------------------------|------------|
| `success`, `thành công`, `matched` | `SUCCESS` |
| `fail`, `failed`, `thất bại` | `FAILED` |
| `reversed`, `hoàn tiền` | `REVERSED` |
| anything else | `PENDING` |

**5d. If not found — MISSING_INTERNAL:**

```python
ReconciliationResult(
    partnerTxnId=partner_txn_id,
    partnerAmount=partner_amount,
    partnerStatus=partner_status,
    reconciliationStatus=MISSING_INTERNAL,
    partnerRecordId=str(partner_record.id),
)
```

### Step 6: Process Missing Partner Records

For each internal record whose `partnerTxnId` was NOT matched by any partner record:

```python
ReconciliationResult(
    partnerTxnId=partner_txn_id,
    internalTxnId=internal_record.id,
    internalAmount=internal_record.amount,
    internalStatus=internal_record.status,
    reconciliationStatus=MISSING_PARTNER,
    internalRecordId=str(internal_record.id),
)
```

### Step 7: Idempotent Write

```python
# Delete any existing results for the same keys
target_ids = [r.id for r in results]
await result_repo.collection.delete_many({"_id": {"$in": target_ids}})

# Insert new results
await result_repo.insert_many(results)
```

**Why delete+insert instead of upsert?** `insert_many` is more performant for batch writes. Keys are deterministic (`partnerTxnId`), so delete+insert is safe and ensures consistency if classification logic changed.

### Step 8: Return Results

Each result contains:
```
partnerTxnId, reconciliationStatus,
partnerAmount vs internalAmount,
partnerStatus vs internalStatus,
partnerRecordId, internalRecordId (if applicable)
```

### Example: Log Output

```
RECONCILIATION COMPLETED — partner=MOMO, 2024-07-07
  - Key: 2407055711887385978413624 → MATCHED (Amt: 259200, Int: 259200)
  - Key: 2407055711887385978413625 → AMOUNT_MISMATCH (Amt: 259200, Int: 100000)
  - Key: internal_only_txn_999 → MISSING_PARTNER (Amt: None, Int: 15000)
```

---

### Scenario 4: Exception During Processing

**Input:** ConfigLoader fails to connect to MongoDB

```
process_file() → ConfigLoader.load_by_partner_type() → Exception
  → except block:
    → emit_file_failed(file_id, "Connection refused")
    → update_status(FAILED)  # best effort
    → return IngestionResult(file_record=file_record, stats=partial_stats, errors=[{"field": "pipeline", ...}])
```
