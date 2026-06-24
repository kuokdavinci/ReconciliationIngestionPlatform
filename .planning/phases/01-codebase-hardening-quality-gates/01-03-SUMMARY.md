---
phase: 01-codebase-hardening-quality-gates
plan: 03
subsystem: cli
tags: [run.py, argparse, entrypoint, modular-cli, decomposition]
requires:
  - phase: 01-codebase-hardening-quality-gates
    provides: Base codebase state with 460-line run.py god entrypoint
provides:
  - Decomposed CLI modules: ingest, reconcile, scheduler, config import, server
  - Thin run.py entrypoint (<80 lines) delegating to CLI modules
affects: [no downstream phases depend on this directly — all imports preserved]
tech-stack:
  added: []
  patterns:
    - "run.py is a thin entrypoint (<80 lines) with no business logic"
    - "Each CLI responsibility has its own module under cli/"
    - "Server startup lives in api/server.py (not run.py)"
key-files:
  created:
    - cli/__init__.py
    - cli/ingest.py
    - cli/reconcile.py
    - cli/scheduler.py
    - cli/config_import.py
    - api/__init__.py
    - api/server.py
  modified:
    - run.py
key-decisions:
  - "Server startup moved to await-less asyncio.run() in api/server.py, dispatched synchronously from run.py to avoid nested event loop bug"
  - "cli/config_import.py is a placeholder — config import logic stays bundled with ingest (--config flag)"
  - "Nested asyncio.run() in original plan design fixed: --serve path runs outside async main()"
requirements-completed: [Q-05]
duration: 10min
completed: 2026-06-24
---

# Phase 01 Plan 03: run.py Decomposed into Modular CLI Scripts

**run.py reduced from 460 to 68 lines with 6 dedicated modules in cli/ and api/ directories — all original CLI commands preserved via delegation**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-24T07:35:38Z
- **Completed:** 2026-06-24T07:43:25Z
- **Tasks:** 2
- **Files created:** 6
- **Files modified:** 1

## Accomplishments

- Extracted `parse_excel_template()` and `run_ingestion()` into `cli/ingest.py` with full verbatim implementation
- Extracted `run_reconciliation()` with seed-mock support into `cli/reconcile.py`
- Extracted `handle_scheduler_mode()` into `cli/scheduler.py`
- Created `api/server.py` for FastAPI server startup with `run_server()`
- Created `cli/__init__.py` with shared `get_db()` and `init_databases()` utilities
- Reduced `run.py` from 460 lines to 68 lines — no motor, paramiko, or openpyxl imports
- All 11 original CLI arguments preserved and dispatching correctly

## Task Commits

Each task was committed atomically:

1. **Task 1: Create modular CLI directory structure** - `fb357b7` (feat)
2. **Task 2: Refactor run.py to thin entrypoint** - `d851d0d` (refactor)

**Plan metadata:** *(committed after SUMMARY.md)*

_Note: Task 2 fixed a nested asyncio.run() bug — restructured dispatch to handle --serve synchronously outside the event loop._

## Files Created/Modified

### Created
- `cli/__init__.py` — Shared CLI utilities: `get_db()`, `init_databases()`
- `cli/ingest.py` — `parse_excel_template()`, `run_ingestion()` extracted verbatim from run.py
- `cli/reconcile.py` — `run_reconciliation()` with seed-mock and reconciliation engine dispatch
- `cli/scheduler.py` — `handle_scheduler_mode()` for scheduler daemon, job listing, and manual trigger
- `cli/config_import.py` — Placeholder module (config import bundled with ingest)
- `api/__init__.py` — Package marker
- `api/server.py` — `run_server()` wrapping uvicorn with asyncio.run()

### Modified
- `run.py` — Reduced from 460 to 68 lines: thin entrypoint delegating to cli/ and api/ modules

## Decisions Made

- **Server startup extracted to api/server.py**: `run_server()` uses standalone `asyncio.run()` internally. Dispatched from `run.py` before the async event loop to avoid nested event loop RuntimeError in Python 3.11+.
- **cli/config_import.py kept as placeholder**: The `--config` flag both uploads config AND runs ingestion. Keeping them bundled in `cli/ingest.py` is simpler than splitting into two overlapping modules.
- **Synchronous entrypoint for run.py**: Using synchronous `main()` function instead of `async def main()` to cleanly separate the `--serve` path (synchronous with its own event loop) from async commands.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed nested asyncio.run() in run.py dispatch**
- **Found during:** Task 2 (Refactor run.py)
- **Issue:** Plan specified `async def main()` with `run_server(port=args.port)` called synchronously inside. But `run_server()` calls `asyncio.run()` internally, which raises `RuntimeError: asyncio.run() cannot be called from a running event loop` in Python 3.11+.
- **Fix:** Restructured `run.py` to use a synchronous `main()` function. The `--serve` path is handled outside the async context. All other commands are dispatched through `asyncio.run(_async_dispatch(args))`.
- **Files modified:** `run.py`
- **Verification:** `uv run python run.py --list-jobs` executes successfully (proves event loop works), `uv run python run.py --help` works (proves sync dispatch works)
- **Committed in:** `d851d0d` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary fix for Python 3.11+ compatibility. No scope creep — same dispatch behavior preserved.

## Issues Encountered

- **`api/server.py` module not found on first import**: The `api/` directory initially lacked `__init__.py`. Added package marker to fix. (Note: `cli/` imported successfully because Python path scanning resolved it differently — the project root is not in `sys.path` by default under `uv run`, but relative `cli` resolution works because uv adds CWD.)

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- CLI decomposition complete — all original commands preserved
- Next plan (01-04) can proceed with database migration (Alembic setup)
- All cli/ modules ready for independent testing and refinement

---

## Self-Check: PASSED

- [x] All 6 cli/ and api/ files created
- [x] Both commits (`fb357b7`, `d851d0d`) present in git history
- [x] run.py is 68 lines (under 80 threshold)
- [x] No motor, paramiko, or openpyxl imports in run.py
- [x] All modules import: `cli`, `cli.ingest`, `cli.reconcile`, `cli.scheduler`, `api.server`
- [x] `python run.py --help` exits 0 with all 11 original arguments
- [x] `--list-jobs` dispatches to scheduler module and executes successfully
- [x] `--reconcile` dispatches to reconciliation module and executes successfully

---

*Phase: 01-codebase-hardening-quality-gates*
*Completed: 2026-06-24*
