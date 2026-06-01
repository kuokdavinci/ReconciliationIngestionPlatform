# Phase 9: Transaction Content Reconciliation & Mock Internal DB

## Goal
Implement a deterministic reconciliation engine that matches ingested partner transaction data with internal system transactions (using a mock internal database repository), computes reconciliation statuses, detects discrepancies, and stores results in a dedicated database collection.

---

## Architectural Design

```
            Partner Data
                 │ (via Ingestion Pipeline)
                 ▼
         Raw Storage (Mongo)  ◀─── [data_container]
                 │
                 │   [Reconciliation Engine] (matches key `partnerTxnId`)
                 ├─── compares partner data with internal transactions
                 │
  [Internal Transaction System] ◀─── [internal_transaction] (Mock DB)
                 │
                 ▼
     [reconciliation_result] collection (matched / discrepant reports)
```

---

## Data Models

### 1. Internal Transaction Collection (`internal_transaction`)
Represents the internal database (Source of Truth).
```json
{
  "_id": "string",
  "partner": "MOMO | ZALOPAY | ...",
  "partnerTxnId": "string",
  "amount": "Decimal128",
  "currency": "VND",
  "status": "SUCCESS | FAILED | PENDING | REVERSED",
  "transactionTime": "ISODate",
  "createdAt": "ISODate",
  "updatedAt": "ISODate"
}
```

### 2. Reconciliation Result Collection (`reconciliation_result`)
Stores the reconciliation execution output.
```json
{
  "_id": "string",
  "partnerTxnId": "string",
  "internalTxnId": "string",
  "partnerAmount": "Decimal128",
  "internalAmount": "Decimal128",
  "partnerStatus": "string",
  "internalStatus": "string",
  "reconciliationStatus": "MATCHED | AMOUNT_MISMATCH | STATUS_MISMATCH | MULTIPLE_MISMATCH | MISSING_INTERNAL | MISSING_PARTNER",
  "partnerRecordId": "string",
  "internalRecordId": "string",
  "createdAt": "ISODate"
}
```

---

## Matching & Classification Rules

1. **Reconciliation Key**: `partnerTxnId` (mapped from `partnerData.trace`, `partnerData.extra.vspTransId`, or standard transaction IDs).
2. **Duplicate Handling**: If multiple internal records exist for the same `partnerTxnId`, the latest one based on `updatedAt` is selected.
3. **Status Normalization**: Partner statuses are normalized to `SUCCESS | FAILED | PENDING` to match internal enums before comparison.
4. **Tolerance**: 
   * **Amount**: Absolute comparison (tolerance = 0).
   * **Time**: Only used for daily partitioning/filtering, not for matching decisions.

### Classification Logic
* `MATCHED`: Key matches, amount matches, status matches.
* `AMOUNT_MISMATCH`: Key matches, amount differs (status matching is ignored).
* `STATUS_MISMATCH`: Key matches, amount matches, status differs.
* `MULTIPLE_MISMATCH`: Key matches, both amount and status differ.
* `MISSING_INTERNAL`: Partner record exists but no matching internal transaction is found.
* `MISSING_PARTNER`: Internal record exists but no matching partner transaction was ingested.

---

## Proposed Changes

### 1. Core Changes
* **`src/core/enums.py`**: Add `ReconciliationStatus` enum.
* **`src/models/internal_transaction.py`**: Define `InternalTransaction` Pydantic model and repository.
* **`src/models/reconciliation_result.py`**: Define `ReconciliationResult` Pydantic model and repository.

### 2. Reconciliation Engine
* **`src/reconciliation/engine.py`**: Build `ReconciliationEngine` service containing the match and classification logic.

### 3. CLI Trigger
* **`run.py`**: Add `--reconcile` and mock data seeding flags:
  `python run.py reconcile --partner MOMO --date 2024-07-07`

---

## Verification Plan

### Automated Tests (`tests/test_reconciliation.py`)
* Verify matching and mismatch statuses (`MATCHED`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `MULTIPLE_MISMATCH`).
* Verify missing cases (`MISSING_INTERNAL`, `MISSING_PARTNER`).
* Verify duplicate handling (latest updated transaction wins).
