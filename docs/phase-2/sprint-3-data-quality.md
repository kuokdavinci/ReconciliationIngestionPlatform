# Sprint 3 — Data quality and quarantine

## Status and boundary

**Workstream A is complete** for EDA/profile/provenance/frozen-baseline,
controlled-mutation, and coverage-handoff evidence for the Fraud Detection
Dataset. **Workstream B is now implemented** for the shared runtime quality
contract, deterministic file/row gate, duplicate classification, bounded
source-unit result, and conflict quarantine routing. Workstreams C–F remain
handoffs; this document does not promote statistical or fraud semantics into
automatic rejection.

The full-profile baseline is version `3`, SHA-256
`e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6`, with
`valid=1,000,000`, `rejected=0`, and `duplicate=0`. Its deterministic quality
decision is `PASS`; amount IQR remains a descriptive observation and is not a
quality-gate rule. The 26 focused profile tests, including controlled
mutations, pass.

The notebook remains unchanged and Kaggle-only. Any notebook improvements are
suggestions, not implementation work.

The executable profile is generic (`scripts/eda/quality_profile.py`).
`scripts/eda/fraud_detection_dataset.py` supplies only the current source
schema configuration, while `scripts/eda/profile_fraud_dataset.py` is the
dataset-specific runner. Fraud-label, coordinate, and entity-consistency
findings remain EDA observations and are not canonical ingestion rules.

## Frozen source-to-canonical baseline

The 17-column source schema is:

`transaction_id`, `timestamp`, `customer_id`, `card_id`, `device_id`,
`ip_address`, `merchant_id`, `merchant_category`, `merchant_country`,
`merchant_city`, `merchant_latitude`, `merchant_longitude`,
`transaction_type`, `amount`, `currency`, `is_fraud`, `fraud_type`.

The frozen benchmark maps `transaction_id → id` (required), `amount → amount`
(required `DECIMAL`), and `currency → currency` (required `STRING`). It sets
`status ← SUCCESS`. It retains timestamp as `extra.sourceTimestamp`; the
intended canonical destination is `transDate`, but ISO timezone parsing is not
yet supported by the current baseline. Customer/card/device/IP,
merchant/category/country/city/coordinates/transaction type, and fraud label
are retained in `extra.*`. `fraud_type` is intentionally unmapped and is not a
canonical field.

EDA uniqueness is local to this source file. Runtime persistence uniqueness is
`(identify, ingestion_key)`, so its idempotency scope is different.

## Workstream A coverage handoff

| Candidate | Status | Current boundary | Owner |
|---|---|---|---|
| Required ID/amount/currency and Decimal conversion | COVERED | Mapping, normalizer, validator | A closed; B/C maintain |
| Negative amount; zero valid | COVERED | Validator rejects negative values and accepts zero | A closed; C maintain |
| ISO timezone timestamp to `transDate` | GAP | Timestamp remains `extra.sourceTimestamp` | C |
| Equivalent duplicate/idempotency | COVERED | PostgreSQL key conflict plus canonical business-payload SHA-256 classification | B closed; D/F operate |
| Conflicting duplicate | COVERED | Bulk payload comparison, typed evidence, quarantine, and source-unit hold | B closed; D owns lifecycle |
| Header/schema drift | COVERED | Runtime file gate distinguishes append-only warning from breaking/fatal drift | B closed; C maintains types |
| Amount IQR | DO_NOT_PROMOTE | Descriptive observation only; not a profile decision rule | Partner/business contract |
| Fraud semantics | DO_NOT_PROMOTE | Monitoring candidate only | Partner/business contract |
| Card/customer, merchant/location, coordinate semantics | DO_NOT_PROMOTE | Monitoring candidates only | Partner/business contract |
| Temporal volume | DO_NOT_PROMOTE | Monitoring candidate only | Partner/business contract |

## Workstreams B–F

### B — Quality contract and gate — implemented

Implemented in `src/domain/ingestion/quality.py`,
`src/domain/partner_transaction/duplicates.py`, application policy/serialization
modules, and `src/pipeline/quality_gate.py`. Approved rule codes, deterministic
decision semantics, structural gating, duplicate payload comparison, conflict
quarantine, bounded Airflow result, tests, and benchmark evidence are documented in
[`sprint-3-workstream-b-quality-contract.md`](sprint-3-workstream-b-quality-contract.md).
EDA does not replace mapping or business approval.

The latest 1M-row quick-win comparison shows a 12.0% reduction in row-preparation
time and an 88.7% reduction in duplicate-row mapping time after removing the
`model_docs` list and projecting only fingerprint fields. PostgreSQL conflict
lookup is now implemented with a transaction-scoped temporary key table loaded
by `COPY` and read through one set-based `JOIN`; 1M-row equivalent and
conflicting duplicate runs complete at 6,944 and 5,169 rows/s respectively.
The clean-path regression investigation found per-row Pydantic
`QualityEvaluation` allocation as the dominant avoidable overhead. The
context-free valid-evaluation fast path reduced the 1M regression from 13.45%
to 9.01% against the stored pre-Workstream-B baseline, within the acceptance
target.

### C — Normalization and validation contract

Specify stable structured validation errors and complete timezone-aware
`transDate` parsing. Preserve the current Decimal and negative-amount
boundaries while adding contract-backed tests.

### D — Quarantine lifecycle

Define retention, operator resolution, reprocessing, and lifecycle evidence for
the sanitized row rejects and conflicting duplicates already routed by
Workstream B.

### E — Operator and approval flow

Define review ownership, approval/rejection actions, counters, and escalation
for `REVIEW` outcomes.

### F — Observability and production acceptance

Define monitoring baselines, alerts, dashboards, partner sign-off, and
production acceptance evidence. Statistical or semantic candidates must stay
out of automatic rejection until that contract exists.

## Fixture and test guidance

Use small, deterministic CSV mutations generated as `tmp_path` files; do not
add or depend on external raw datasets. Cover missing required fields, ISO
timestamp failure, unparseable/negative amount, equivalent and conflicting
duplicates, schema drift, and descriptive amount outliers. The generic profile
test file is `tests/test_quality_profile.py`; fraud-semantic findings belong in
the Kaggle EDA notebook and its review notes.
