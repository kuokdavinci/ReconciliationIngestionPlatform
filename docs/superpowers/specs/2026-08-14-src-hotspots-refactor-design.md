# Source Hotspots Refactor Design

## Goal

Reduce oversized functions and duplicated ownership in `src/` while preserving the existing ingestion, review, reconciliation, Airflow, API, and recovery behavior.

## Scope

This refactor covers the highest-risk findings from the source review:

1. Extract shared API dependencies, query validation, and review-scope helpers.
2. Make reconciliation backend selection explicit and isolate PostgreSQL/document-store execution paths.
3. Split stream execution into lifecycle, paginated-stream, file-stream, and failure handling components.
4. Move review proposal/packet orchestration out of `config_health` and consolidate it with application review workflows.
5. Split post-approval reprocessing into replay and reconciliation lifecycle components.
6. Canonicalize business-date and file-hash helpers where behavior is identical, while preserving adapter-specific wrappers.

The `infrastructure/persistence` versus `infrastructure/postgres` directory move is intentionally deferred until import and deployment references can be migrated in one isolated task. The existing domain/infrastructure bounded-context split and reader/repository interface implementations remain unchanged.

## Architecture

API modules will own transport concerns only: request parsing, dependency lookup, and response serialization. Review scope classification and proposal creation remain application concerns. `config_health` will return health/decision data and will not create review artifacts.

`ReconciliationEngine.reconcile` will remain the public use-case entry point, but backend execution will be selected from explicit injected capability/adapter wiring. The engine will not inspect whether repository methods are mocks. Stream execution will use a small dispatcher that delegates API pagination and file ingestion to focused runners while preserving the current runtime/checkpoint contracts.

## Behavior and error handling

- Existing public function signatures and API response shapes remain compatible unless a test proves that a private helper can be removed.
- Existing checkpoint, review-gate, retry, and post-approval status transitions remain unchanged.
- Repository failures continue to propagate through the current error/result contracts.
- New extracted components receive dependencies explicitly; no new global service locator is introduced.
- Any behavior change discovered by tests is treated as a blocker for that task rather than silently “simplified.”

## Testing strategy

- Add or update focused tests before each production refactor and verify the test fails for the intended reason.
- Run the narrow affected test module after each task.
- Run Ruff, mypy for `src/`, the full backend CI suite, and the ingestion suite at the end.
- Refresh and inspect the codegraph after structural changes.

## Non-goals

- Do not remove domain/infrastructure layers.
- Do not delete reader/repository methods merely because multiple adapters implement the same port.
- Do not change database schemas, API contracts, sprint documentation, or unrelated worktree changes.
