# Complete Architecture Migration

## Goal

Migrate all consumers from `src.models`, move review reprocessing into its own application module, split oversized application services by use case, and remove the old compatibility package without changing external API response contracts.

## Tasks

- [x] Migrate tests and scripts from `src.models` to `src.domain` and `src.infrastructure`.
- [x] Move review reprocessing implementation out of `actions.py`; keep approval/rejection actions as the public boundary.
- [x] Split automation, mapping review, and Copilot code by cohesive use case while preserving imports used by API adapters.
- [x] Remove `src/models` and update architecture checks, documentation, and CI references.
- [x] Refresh codegraph and run Ruff, mypy, targeted tests, and the full backend/ingestion suites.

## Done When

- No production, test, script, or DAG import references `src.models`.
- No application module imports a private reprocessing function from another application module.
- The old compatibility package is removed.
- All relevant checks pass and the migration is pushed on the dedicated branch.

## Notes

Keep `domain` free of adapters, keep persistence/workflow clients in `infrastructure`, and preserve API-facing behavior while changing internal module ownership.
