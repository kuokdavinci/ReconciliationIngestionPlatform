---
phase: 01-codebase-hardening-quality-gates
plan: 04
subsystem: database
tags: [alembic, postgresql, asyncpg, sqlalchemy, migration]

# Dependency graph
requires:
  - phase: 01-01
    provides: alembic dependency in pyproject.toml
provides:
  - Alembic migration system with async support
  - Initial migration capturing partner_transaction, internal_transaction, reconciliation_result
  - Programmatic Alembic runner for FastAPI lifespan startup
affects: [03-mongodb-postgresql-migration]

# Tech tracking
tech-stack:
  added: [alembic]
  patterns:
    - Programmatic Alembic migration via config.attributes['connection']
    - Async-compatible env.py supporting both CLI and programmatic modes

key-files:
  created:
    - alembic.ini
    - alembic/env.py
    - alembic/script.py.mako
    - alembic/versions/0001_initial_schema.py
  modified:
    - src/models/postgres.py

key-decisions:
  - "Programmatic Alembic runner reuses existing async connection via config.attributes['connection'] instead of creating a new engine — avoids asyncio.run() from within running event loop"
  - "UNLOGGED tables changed from default to opt-in (use_unlogged=False) — durability-first production default"

patterns-established:
  - "Database migrations: Alembic with async support, usable both from CLI (alembic upgrade head) and programmatically from FastAPI lifespan"
  - "Migration runner: _run_alembic_upgrade() receives sync connection via conn.run_sync(), passes it to env.py via config.attributes"

requirements-completed: [Q-06]

# Metrics
duration: 12min
completed: 2026-06-24
---

# Phase 01 Codebase Hardening: Plan 04 Summary

**Alembic migration system replacing Base.metadata.create_all with initial schema migration and configurable UNLOGGED table durability**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-24T14:38:00Z
- **Completed:** 2026-06-24T14:50:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Alembic initialized with async support (asyncpg-compatible env.py)
- Initial migration captures all 3 existing PostgreSQL tables with full schema (columns, types, indexes, defaults)
- `Base.metadata.create_all` removed from `init_postgres_db()` — schema now managed via Alembic migrations
- UNLOGGED table setting changed from silent default to explicit opt-in (`use_unlogged=False` by default)
- env.py supports both CLI mode (`alembic upgrade head`) and programmatic mode via `config.attributes['connection']` — avoids `asyncio.run()` crash from within running event loop

## Commits

1. **Task 1: Initialize Alembic and create initial migration** — `1cde85f` (feat)
2. **Task 2: Remove Base.metadata.create_all and make UNLOGGED configurable** — `d0add9a` (feat)

## Files Created/Modified

### Created
- `alembic.ini` — Alembic configuration with `script_location = alembic` and `sqlalchemy.url`
- `alembic/env.py` — Async-compatible environment with `target_metadata = Base.metadata` and dual-mode support (CLI + programmatic)
- `alembic/script.py.mako` — Migration script template
- `alembic/versions/0001_initial_schema.py` — Initial migration creating `partner_transaction`, `internal_transaction`, and `reconciliation_result` tables with all columns, indexes, and server defaults

### Modified
- `src/models/postgres.py` — Replaced `Base.metadata.create_all()` with Alembic-based `_run_alembic_upgrade()`; added `use_unlogged: bool = False` parameter; UNLOGGED ALTER TABLE only executes when explicitly enabled

## Decisions Made
- **Programmatic Alembic runner:** Calling `alembic.command.upgrade()` from inside an async FastAPI lifespan would fail because `env.py` uses `asyncio.run()`. Solved by passing the existing connection via `config.attributes['connection']` and having `env.py` use it directly when present, bypassing the async engine creation.
- **UNLOGGED opt-in default:** Changed from silent default to explicit `use_unlogged=False` to satisfy T-04-01 threat mitigation. Operators must explicitly acknowledge the durability trade-off.

## Deviations from Plan
None — plan executed exactly as written.

## Issues Encountered
- **ModuleNotFoundError for `src`:** `alembic env.py` couldn't find the `src` module when run from the project root. Fixed by adding `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` in `env.py`.
- **Async event loop conflict:** Calling `command.upgrade()` from an async function crashes with `RuntimeError: asyncio.run() cannot be called from a running event loop`. Resolved by enhancing `env.py` to accept a pre-existing connection from `config.attributes['connection']` and calling `do_run_migrations(target_connection)` synchronously in that case.

## Verification

- ✅ `alembic upgrade head --sql` produces valid DDL for all 3 tables with indexes, types, and server defaults
- ✅ `grep 'create_all' src/models/postgres.py` returns nothing
- ✅ `grep 'use_unlogged' src/models/postgres.py` matches
- ✅ No Base.metadata.create_all — schema migration is Alembic-managed
- ✅ All callers (`cli/__init__.py`, `src/api/__init__.py`, `tests/conftest.py`) call `init_postgres_db(url)` without `use_unlogged`, which defaults to `False`

## Next Phase Readiness
- Alembic infrastructure is in place for all future schema changes
- The 3 existing tables are captured in the initial migration — downstream phases can add new migrations via `alembic revision --autogenerate`
- `init_postgres_db` signature changed (added `use_unlogged` parameter) — callers with keyword arguments may need updating if any exist outside this codebase

---
*Phase: 01-codebase-hardening-quality-gates*
*Completed: 2026-06-24*
