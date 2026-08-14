# Task 3 implementer report

- Commit: `b23b793` (`refactor: add explicit reconciliation executors`)
- TDD RED: `rtk proxy .venv/bin/pytest -q tests/test_reconciliation.py::test_reconciliation_accepts_explicit_document_backend` failed with `TypeError: ReconciliationEngine.__init__() got an unexpected keyword argument 'backend'` before the explicit backend contract existed.
- TDD GREEN: `rtk proxy .venv/bin/pytest -q tests/test_reconciliation.py tests/test_reconciliation_architecture.py tests/test_reconciliation_run_architecture.py` — `32 passed in 0.19s`.
- Ruff: focused Task 3 source/tests — `All checks passed!`.
- Mypy: focused source check reports 8 typing errors in `src/reconciliation/document_executor.py`; no additional test run was performed after this report because the task was explicitly stopped after focused tests.
- Files: explicit `ReconciliationExecutor` port; `DocumentReconciliationExecutor`; `PostgresReconciliationExecutor`; thin explicit-backend `ReconciliationEngine`; PostgreSQL composition injection; reconciliation test callers and architecture assertion.
- Codegraph: synced after the structural change (`2 added`, `5 modified`).
- Scope: TODO.md and unrelated dirty/untracked documentation were not staged.

## Fix round 1

- Root cause: the document executor's Mongo conversion hooks were hidden behind broad repository protocols; Pydantic aliases and monetary values were not expressed in the factory types; and the diagnostic result fallback used an un-narrowed result union.
- Fix: added narrow document-capability protocols/type guards, used the `_id` alias and `Decimal` types for `ReconciliationResult`, and added a typed result-key helper plus explicit query/key narrowing. Runtime matching, batching, deletion, and mapping paths are unchanged.
- Mypy RED reproduced: the focused source check reported 8 errors in `document_executor.py` before the fix.
- Mypy GREEN: `rtk proxy .venv/bin/mypy src/reconciliation/engine.py src/reconciliation/document_executor.py src/reconciliation/postgres_executor.py src/domain/reconciliation/ports.py src/infrastructure/reconciliation/composition.py --show-error-codes` — `Success: no issues found in 5 source files`.
- Focused tests: `rtk proxy .venv/bin/pytest -q tests/test_reconciliation.py tests/test_reconciliation_architecture.py tests/test_reconciliation_run_architecture.py` — `32 passed in 0.20s`.
- Ruff: focused Task 3 source/tests — `All checks passed!`.
- Fix commit: `5c78924` (`fix: type reconciliation document executor`).

## Fix round 2

- Fix commit: `8fa838e` (`fix: preserve reconciliation writes and scoped deletion`).
- Root cause: result deletion was defined but not deferred to the first non-empty write, and completed write tasks were pruned before `asyncio.gather()` could retrieve failures. The typed internal-reader port also incorrectly used the reconciliation-output union, making the PostgreSQL executor incompatible with the executor protocol.
- Fix: route unmapped, matched/unmatched partner, unmatched internal, and final buffers through one non-empty flush helper; delete once immediately before the first write; retain every write task for `asyncio.gather()`; keep the `__anext__` fallback and typed aliases/Literal; separate internal-reader output typing and annotate the PostgreSQL executor with `ReconciliationOutput` safely.
- Regression evidence: `test_reconciliation_reraises_document_write_failure` now propagates `insert_many` errors; empty input and pending-only input do not delete; existing scope tests verify exactly-once deletion.
- Focused tests: `rtk proxy .venv/bin/pytest -q tests/test_reconciliation.py tests/test_reconciliation_architecture.py tests/test_reconciliation_run_architecture.py` — `35 passed in 0.20s`.
- Ruff: focused Task 3 source/tests — `All checks passed!`.
- Mypy: focused Task 3 source/composition check — `Success: no issues found in 5 source files`.
- Scope: only the five Task 3 implementation/test files were included in `8fa838e`; TODO.md and unrelated dirty/untracked documentation were not staged.
