---
phase: 01-codebase-hardening-quality-gates
plan: 01
subsystem: testing
tags: [ruff, mypy, pytest, ci, alembic, type-checking]

requires:
  - phase: project-initialization
    provides: Existing pyproject.toml and CI workflow files
provides:
  - Strict Ruff lint rules with F821 (undefined name) re-enabled
  - Per-module mypy opt-out instead of global ignore_errors
  - CI runs full 48-file test suite excluding E2E tests
  - mypy type checking step in CI pipeline
  - Alembic migration dependency available for future use
affects: [01-04, 02, 03]

tech-stack:
  added: [alembic>=1.14.0]
  patterns:
    - "Per-module mypy opt-out: new modules checked strictly, legacy modules in override list"
    - "CI runs full test suite minus E2E, with AI_API_KEY env var for analysis tests"

key-files:
  modified:
    - pyproject.toml
    - .github/workflows/backend-quality.yml

key-decisions:
  - "Per-module mypy overrides for src.api.*, src.analysis.*, src.reconciliation.engine, src.models.postgres — keeps type checking enabled globally while silencing known-problematic modules"
  - "E2E tests excluded from CI via --ignore flags — they require real external services"
  - "AI_API_KEY set to sk-test-fake-key for CI — no real credentials exposed"

patterns-established:
  - "Lint gates: Ruff F821 (undefined name) errors block CI"
  - "Type checking: mypy runs on src/ with per-module opt-outs"
  - "Test isolation: E2E tests excluded from CI, run separately in eval.yml"

requirements-completed: [Q-01, Q-02]

duration: 11min
completed: 2026-06-24
---

# Phase 1 Plan 1: Quality Gates Hardening Summary

**Strict Ruff lint rules, per-module mypy configuration, expanded CI coverage with full test suite and type checking, alembic dependency added**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-24T07:37:00Z (approx)
- **Completed:** 2026-06-24T07:48:00Z (approx)
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Removed F821 from Ruff ignore list so undefined name errors now block CI
- Replaced global mypy `ignore_errors = true` with per-module overrides for legacy modules — new modules get strict type checking
- Expanded CI test step from an unspecified `uv run pytest` to `pytest tests/` with explicit E2E test exclusions and AI_API_KEY env var
- Added mypy type checking step to CI pipeline, running after lint
- Added `alembic>=1.14.0` dependency for the upcoming Alembic migration system (Plan 04)

## Task Commits

Each task was committed atomically:

1. **Task 1: Tighten Ruff lint rules and mypy configuration** — `029e3bc` (chore)
2. **Task 2: Expand CI to run full test suite** — `c4f8a80` (ci)

## Files Created/Modified

- `pyproject.toml` — F821 removed from Ruff ignore list, mypy moved to per-module overrides, alembic added to dependencies
- `.github/workflows/backend-quality.yml` — Test step expanded to run full suite with E2E exclusions, mypy step added, AI_API_KEY env var added

## Decisions Made

- Used `[[tool.mypy.overrides]]` with per-module `ignore_errors = true` for `src.api.*`, `src.analysis.*`, `src.reconciliation.engine`, and `src.models.postgres` — enables strict checking everywhere else while silencing known-problematic modules
- Excluded `tests/test_analysis_e2e.py` and `tests/test_phase8.py` from CI test run — these are E2E tests requiring external services
- Set `AI_API_KEY: "sk-test-fake-key"` as a test-only env var — matches the pattern already used in `eval.yml`

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Quality gates are now stricter — Ruff F821 errors and mypy type checking will catch real issues
- CI now validates the full test suite (API, ingestion, reconciliation, config) on every push
- Alembic dependency is available for migration system implementation in Plan 04
- Ready for Plan 02 (auth/security hardening) and Plan 03 (docs drift resolution)

---

## Self-Check: PASSED

- ✅ `pyproject.toml` exists — modified, 72 lines, 3 changes verified
- ✅ `.github/workflows/backend-quality.yml` exists — modified, 61 lines, 3 changes verified
- ✅ Commit `029e3bc` — Task 1 (chore: tighten Ruff and mypy)
- ✅ Commit `c4f8a80` — Task 2 (ci: expand CI test suite)
- ✅ No accidental file deletions detected
- ✅ No untracked files (all artifacts intentional and tracked)

---

*Phase: 01-codebase-hardening-quality-gates*
*Completed: 2026-06-24*
