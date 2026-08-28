## Reconciliation logic alignment

### Sprint 3 — finalize the contract

- [x] Define the canonical normalized `reconciliation_key` used by both sides; document that `partner_trace`/`partner_txn_id` are semantic fields and `vspTransId` is only a partner-specific source input. See `docs/phase-2/sprint-3-reconciliation-key-evidence.md`.
- [x] Define the uniqueness scope for that key: `(partner, key)` or `(partner, reconciliation_date, key)`; do not include `source_file_id` unless replacement files represent different logical transactions. Sprint 3 uses `(partner, reconciliation_key)`.
- [x] Audit partner and internal data for null/blank keys, duplicate keys, and conflicting fallback values before adding constraints. See the bounded Docker snapshot in the evidence document.
- [x] Confirm the existing constraints are being used for the intended purpose: `ingestion_key` for ingest idempotency, versus `reconciliation_key` for business matching.
- [x] Record the duplicate rate, invalid-key rate, and proposed constraint/index contract as Sprint 3 acceptance evidence.

### Post-Sprint 3 — implement the aligned reconciliation path

The items below remain a follow-up migration backlog. They are intentionally
not part of the Sprint 3 data-quality/quarantine closeout because they require
PostgreSQL schema changes, duplicate remediation, rollout validation, and a
benchmark decision before enforcement.

- [ ] Add a persisted normalized `reconciliation_key` to both transaction models, backfill it, and validate the backfill before enforcing constraints.
- [ ] Add the appropriate unique constraint only after duplicate remediation; preserve a version/history model if internal transactions can legitimately be corrected or repeated.
- [ ] Add indexes for the actual access path, at minimum partner/date/key on both transaction tables.
- [ ] Update the PostgreSQL reconciliation query to join on the canonical key rather than recomputing fallback logic inside the query.
- [ ] Compare currency together with amount and status; add an explicit `CURRENCY_MISMATCH` result when required.
- [ ] Separate `PENDING` from unknown/invalid statuses; unknown statuses must not become a successful `MATCHED` result.
- [ ] Route blank/invalid keys to an explicit invalid-key or quarantine outcome instead of treating them only as missing-side records.
- [ ] Detect duplicate keys before the join and return an `AMBIGUOUS_MATCH`/duplicate-key outcome; do not silently resolve duplicates with `ROW_NUMBER()` unless the business rule explicitly says “latest wins”.
- [ ] Add reconciliation-run isolation using `reconciliation_run_id` plus a lock or equivalent concurrency control for the same partner/date scope.
- [ ] Narrow the CTE projections and avoid loading the entire result set into memory when the result can be paginated or streamed.

### Verification and rollout

- [ ] Add unit and integration tests for currency mismatch, unknown status, null key, duplicate key, replacement scope, and concurrent runs.
- [ ] Run `EXPLAIN (ANALYZE, BUFFERS)` on representative full-snapshot and incremental datasets after the schema/query changes.
- [ ] Backfill and constraint migration must fail safely with a duplicate report; do not enable the unique constraint while unresolved duplicates remain.
- [ ] Re-run the 1M-row benchmark and compare correctness counters as well as elapsed time/throughput before changing runtime defaults.
