# Sprint 3 — Data quality and quarantine

Canonical navigation: [Sprint 3 index](sprint-3-index.md). This document is
the sprint boundary and handoff summary; detailed B/C contracts and evidence
live in their dedicated documents.

## Status and boundary

**Workstream A is complete** for EDA/profile/provenance/frozen-baseline,
controlled-mutation, and coverage-handoff evidence for the Fraud Detection
Dataset. **Workstream B is now implemented** for the shared runtime quality
contract, deterministic file/row gate, duplicate classification, bounded
source-unit result, and conflict quarantine routing. **Workstream C is
`implemented; full-dataset v2 evidence captured`** for the normalization and
validation contract. **Workstream D is implemented at the application,
persistence, production composition, API, audit, and source-unit resume
contract level; production
acceptance remains pending.** Workstreams E–F remain handoffs; this document
does not promote statistical or fraud semantics into automatic rejection.

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

The Workstream C benchmark v2 mapping maps `transaction_id → id` (required),
`timestamp → transDate` (required `DATE`), `amount → amount` (required
`DECIMAL`), and `currency → currency` (required `STRING`). It sets `status ←
SUCCESS`. ISO `Z` and offset timestamps are normalized to UTC-aware canonical
values, while the four accepted legacy formats remain naive. The frozen v1
benchmark artifacts remain unchanged. Customer/card/device/IP,
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
| ISO timezone timestamp to `transDate` | COVERED | Benchmark v2 mapping, UTC-aware normalizer, validator, persistence boundary, normal/fast parity tests | C contract; D operates routed rejects |
| Equivalent duplicate/idempotency | COVERED | PostgreSQL key conflict plus canonical business-payload SHA-256 classification | B closed; D/F operate |
| Conflicting duplicate | COVERED | Bulk payload comparison, typed evidence, quarantine, and source-unit hold | B closed; D owns lifecycle |
| Header/schema drift | COVERED | Runtime file gate distinguishes append-only warning from breaking/fatal drift | B closed; C maintains types |
| Amount IQR | DO_NOT_PROMOTE | Descriptive observation only; not a profile decision rule | Partner/business contract |
| Fraud semantics | DO_NOT_PROMOTE | Monitoring candidate only | Partner/business contract |
| Card/customer, merchant/location, coordinate semantics | DO_NOT_PROMOTE | Monitoring candidates only | Partner/business contract |
| Temporal volume | DO_NOT_PROMOTE | Monitoring candidate only | Partner/business contract |

## Workstreams B–F

### B — Quality contract and gate — implemented

Workstream B owns rule codes, deterministic file/row gates, duplicate payload
classification, bounded runtime outcomes and conflict routing. The full rule
registry, decision matrix, fingerprint contract and performance evidence are
kept in [`sprint-3-workstream-b-quality-contract.md`](sprint-3-workstream-b-quality-contract.md).

### C — Normalization and validation contract — implemented

Workstream C maps the source timestamp to required `transDate`, normalizes ISO
and offset timestamps to UTC-aware values, preserves the legacy date formats,
and keeps normal/fast behavior equivalent. The focused contract run passed
242 tests, and the full 1M-row v2 ingestion benchmark passed on 2026-08-26.
Details and reproducible artifacts are in
[`sprint-3-workstream-c-normalization-validation.md`](sprint-3-workstream-c-normalization-validation.md)
and [`sprint-3-workstream-c-baseline.md`](sprint-3-workstream-c-baseline.md).

### D — Quarantine lifecycle — implemented

Workstream D now provides the complete contract for a routed quarantine row:

1. A sanitized source row or conflicting duplicate is stored as `PENDING` with
   bounded error/evidence fields.
2. An operator or worker atomically claims it as `REPROCESSING`; a second claim
   cannot process the same record concurrently.
3. The resolver replays the authoritative source row, accepts a corrected row,
   verifies `existingFingerprint` for `ACCEPT_EXISTING`, or requires an
   operator reason for `REJECT`.
4. Deterministic validation failures and retryable persistence failures return to
   `PENDING`; successful, equivalent, accepted-existing, and explicit-reject
   outcomes become terminal `RESOLVED` or `REJECTED` states.
5. Active quarantine blockers hold a source unit. Once all blockers are
   terminal, the production resume entry point reconstructs the durable raw
   unit, advances the checkpoint before cleanup, and reconciles an already
   ingested file without replaying the same conflicting row.
6. Resolution history, bounded audit events, operation counters, API views, and
   terminal retention windows preserve the evidence needed for review.

The implementation spans `src/domain/ingestion/quarantine.py`, the quarantine
repository, the ingestion application services, production composition,
source-row/GridFS adapters, source-unit orchestration, Mongo indexes, and
`/api/v1/quarantine`. The deterministic lifecycle fixture in
`tests/test_quarantine_lifecycle.py` covers invalid input, correction,
equivalent/conflicting duplicates, explicit discard, accept-existing, source
unit hold/resume, checkpoint advancement, one-time reconciliation, and evidence
retention. Runtime wiring and adapter coverage is in
`tests/test_quarantine_runtime_wiring.py`, `tests/test_quarantine_adapters.py`,
and `tests/test_quarantine_source_unit_resume.py`. Workstream D tests are
unit/contract tests; live Mongo/PostgreSQL, Airflow, partner sign-off, and
production acceptance remain Workstream F scope.

### E — Operator and approval flow — pending

Define review ownership, approval/rejection actions, counters, and escalation
for `REVIEW` outcomes. This has not been implemented yet; mapping
`ReviewPacket` approval remains on its existing contract.

### F — Observability and production acceptance — pending

Define data-quality acceptance baselines and the handoff inputs for Sprint 4
observability. Generic stage metrics, structured logs, dashboards, alert
delivery, and the 100k observability benchmark remain outside Sprint 3.
Statistical or semantic candidates must stay out of automatic rejection until
that contract exists.

## Fixture and test guidance

Use small, deterministic CSV mutations generated as `tmp_path` files; do not
add or depend on external raw datasets. Cover missing required fields, ISO
timestamp failure, unparseable/negative amount, equivalent and conflicting
duplicates, schema drift, and descriptive amount outliers. The generic profile
test file is `tests/test_quality_profile.py`; fraud-semantic findings belong in
the Kaggle EDA notebook and its review notes.
