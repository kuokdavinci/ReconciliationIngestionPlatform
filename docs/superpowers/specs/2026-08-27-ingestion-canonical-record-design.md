# Ingestion canonical record design

**Date:** 2026-08-27

**Status:** Proposed; awaiting implementation approval

**Scope:** Ingestion row construction only

## Decision

Remove `fast_mode` as a business/runtime mode from the ingestion pipeline.
Ingestion will always normalize and validate rows once, then create one
lightweight canonical write record. Pydantic `DataContainer` remains available
for read-side models, review validation, and legacy compatibility, but it is
not created for every accepted ingestion row.

The reconciliation `fast_mode` flag is a separate optimization and is out of
scope.

## Why

The current ingestion path has one `Validator` but two materializers:

```text
normal: normalize → build CanonicalTransaction/DataContainer → validate
fast:   normalize → build dict/FastDataContainer → validate
```

The distinction is not a business rule. It only changes object construction.
The benchmark supports keeping the lightweight representation:

| Workload | Current normal | Current fast | Fast improvement |
|---|---:|---:|---:|
| 100k rows, two measured runs | 12.325s | 11.567s | 6.55% |
| 1M rows, one measured run | 125.191s | 114.150s | 9.67% |

Both modes persisted all rows with identical `INGESTED / PASS` accounting.

## Goals

- Have exactly one normalization and validation path for ingestion.
- Keep the measured fast-path throughput benefit.
- Make the object passed to PostgreSQL explicit as a canonical write DTO,
  rather than an apparently unvalidated fast-only model.
- Keep quality errors and quarantine behavior independent of materialization.
- Leave read-side Pydantic models and document-store reconciliation unchanged.

## Non-goals

- No new validation rules or changes to rule precedence.
- No change to PostgreSQL schema, duplicate classification, fingerprints,
  quarantine lifecycle, or source-unit resume behavior.
- No change to `DocumentReconciliationExecutor.fast_mode`.
- No new third-party dependency.

## Proposed flow

```text
source row
  → TransactionNormalizer.normalize()
  → Validator.validate(normalized dict)
  → PartnerTransactionRecord (frozen, slots dataclass)
  → existing batch writer and PostgreSQL mapper
```

`PartnerTransactionRecord` contains the persistence envelope currently shared
by `DataContainer` and `FastDataContainer`: identifiers, partner/workflow
metadata, source lineage, timestamps, ingestion key, and a lightweight partner
payload. Its construction is an internal invariant of `RowProcessor`: only a
row that passed normalization and `Validator` reaches the record builder.

The record builder performs mapping and envelope construction only. It does
not duplicate required-field, amount, status, or timestamp checks. Database
constraints remain the final persistence guard.

`RowOutcome` will expose this record as `record`. `RowOutcome` is an internal
pipeline type, so its old `data_container` field will be removed and all
repository/quarantine callers in this repository will be updated in the same
change. No compatibility alias is needed.

## Module boundaries

### Domain models

- Add neutral `PartnerTransactionRecord` and `PartnerTransactionPayload`
  dataclasses by promoting the current lightweight shape and removing the
  `Fast*` naming.
- Keep `DataContainer` and `PartnerData` as Pydantic read/legacy models.
- Do not add validation logic to the new dataclass.

### Row processing

- Remove `fast_mode` from `RowProcessor` and `RowPipelineExecutor`.
- Validate the normalized dictionary before building the record.
- Build one `PartnerTransactionRecord` for every accepted row.
- Preserve `RowOutcome` quality fields, timing fields, ingestion-key behavior,
  and error serialization.

### Persistence

- Extend the existing mapper/repository type contract to accept the neutral
  record and remove `FastDataContainer`/`FastPartnerData` from the exported
  ingestion write contract.
- Keep read methods returning `DataContainer`; read-side callers and API
  serialization therefore remain unchanged.
- Keep the PostgreSQL write shape byte-for-byte equivalent for equivalent input.

### Configuration and callers

- Remove ingestion `fast_mode` arguments from composition and pipeline wiring.
- Make row validation unconditional; the existing `FetchConfig.validateRows`
  field is retained as a deprecated compatibility field for stored/client
  configuration during this migration, but it no longer changes execution.
- Remove the `validate_rows → fast_mode` branch from automation.
- Leave reconciliation unchanged. Keep
  `src/application/review/runtime_validation.py` on its explicit sampled
  Pydantic validation path; it does not consume `RowProcessor` and is not part
  of the ingestion hot path.

The compatibility field is intentionally temporary. A later API/config
version can remove it after clients no longer send or display it.

## Error handling

- Normalization errors return the existing `RowOutcome(REJECT)` unchanged.
- Validation errors return the same structured `QualityViolation` objects and
  serialized payloads for every caller.
- Record construction is only run after validation. Unexpected construction or
  persistence errors continue through the existing batch failure path.
- Quarantine reprocessing uses the same `RowProcessor` and therefore the same
  canonical record contract as first-pass ingestion.

## Testing and acceptance

1. Update unit tests to assert one canonical write record and remove tests that
   treat fast mode as a separate validation implementation.
2. Keep a compact parity contract covering representative valid, invalid,
   duplicate, and quarantine/reprocess inputs before deleting compatibility
   names.
3. Run the focused ingestion/quality/quarantine suites and the existing
   ingestion integration suite.
4. Repeat the 100k and 1M benchmark with the new single path. Acceptance is:
   - identical row accounting and quality outcomes;
   - no new quarantine or persistence failures;
   - no more than 10% regression from the measured current-fast throughput;
   - no Pydantic model creation in the accepted-row hot path.

## Migration order

1. Introduce the neutral write DTO and mapper support.
2. Move `RowProcessor` and the batch pipeline to the single validated path.
3. Remove ingestion `fast_mode` wiring and make validation unconditional.
4. Update quarantine/replay and test callers.
5. Remove unused `Fast*` implementation names and exports; no compatibility
   aliases are required because all repository consumers are in this codebase.
6. Run the acceptance tests and benchmark before changing documentation status.

This keeps the change focused: one semantic pipeline, one write shape, and no
new strategy/factory hierarchy.
