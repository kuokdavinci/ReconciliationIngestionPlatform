# Sprint 3 — Reconciliation contract evidence

**Status:** Sprint 3 reconciliation contract closed for the data-quality and
quarantine boundary. The persisted-key migration and constraint rollout remain
an explicitly separate Post-Sprint 3 backlog.

## Canonical key contract

The current PostgreSQL reconciliation path uses one normalized business key on
each side. The key is a semantic field, not a universal source-column name:

| Side | Canonical field and source mapping | Scope |
|---|---|---|
| Partner | normalized `partner_trace`; each partner mapping supplies its own identifier (for the original case, `vspTransId` was one such source field) | `(partner, reconciliation_key)` |
| Internal | `partner_txn_id` | `(partner, reconciliation_key)` |

The source mapping must produce a non-blank normalized `partner_trace` (or the
corresponding internal `partner_txn_id`). For legacy partner rows that do not
have the normalized field, the runtime keeps bounded fallbacks in this order:
`partner_metadata.vspTransId` → `partner_id`. `vspTransId` is therefore a
partner-specific legacy/source input, not the platform-wide canonical name.
Each value is trimmed and blank values are ignored. `source_file_id` is not a
business-key component. Replacement files therefore replace the same logical
partner/date slice instead of creating a second identity for the same
transaction.

The normalized `partner_trace` is authoritative when present. A lower-priority
legacy fallback that disagrees is reported by the pre-migration audit, not
silently promoted to a second key. This keeps matching deterministic while the
partner contract is being migrated to a persisted key.

## Demo data audit

The following bounded snapshot was captured from the Docker PostgreSQL demo
before the fixture reset on 2026-08-28:

| Check | Result |
|---|---:|
| Partner transaction rows | 19 |
| Internal transaction rows | 20 |
| Partner invalid/blank keys | 0 |
| Internal invalid/blank keys | 0 |
| Partner duplicate key groups | 0 |
| Internal duplicate key groups | 0 |
| Partner rows in duplicate key groups | 0 |
| Internal rows in duplicate key groups | 0 |
| Fallback conflicts (`partner_trace` vs `partner_id`) | 1 |
| Unknown partner status values | 0 |
| Unknown internal status values | 0 |
| Currency mismatches in reconciliation results | 0 |

The one fallback conflict is resolved by the documented candidate precedence;
no duplicate key group was observed. The snapshot is demo evidence, not
partner acceptance or production data-quality sign-off.

## Existing constraints and proposed access path

- `uq_partner_transaction_identify_ingestion_key` protects ingestion
  idempotency. It is not a reconciliation business-key constraint.
- Primary keys protect row identity on both transaction tables.
- Existing query indexes cover partner/date filtering and result status
  filtering.
- The Post-Sprint 3 migration should add nullable persisted
  `reconciliation_key` columns, validate/backfill them, remediate duplicates,
  then add `(partner, reconciliation_key)` indexes/constraints only after the
  duplicate report is clean. It must be a safe, fail-closed migration.

No PostgreSQL/Alembic schema change is claimed in Sprint 3. This preserves the
sprint boundary and avoids enforcing a unique constraint before remediation.

## Verification and deployment evidence

- Full Python suite: `1346 passed, 18 skipped`.
- Focused Sprint 3 regression: `239 passed`.
- Ruff and mypy: pass (`207 source files`).
- Frontend lint, typecheck and production build: pass.
- Playwright dashboard regression: `8 passed`.
- Playwright live scheduler-first DEMO flow: `1 passed` after the demo fixture
  reset.
- Playwright quarantine operator and batch-fatal contracts: `8 passed`.
- Docker Compose config: pass. Current local runtime has API, MongoDB and
  PostgreSQL healthy; the scheduler-first DEMO run reached `WAITING_REVIEW`.
- Direct DEMO1 run reached `FAILED` with `MISSING_REQUIRED_SOURCE_COLUMN`,
  `qualityDecision=FAIL`, `quarantinedRows=0`, and no review packet. This is the
  expected batch-fatal boundary.

The full Airflow topology pass recorded in Workstream F remains historical
local evidence. It was not re-run in this closeout because the current Docker
session uses the local mock orchestrator and only the API/MongoDB/PostgreSQL
services are running. No staging or production deployment was exercised, and
no production sign-off is claimed.
