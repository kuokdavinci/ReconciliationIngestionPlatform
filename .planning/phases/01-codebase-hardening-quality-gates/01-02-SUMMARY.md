---
phase: 01-codebase-hardening-quality-gates
plan: 02
subsystem: auth
tags: [auth, docs, require-actor, frontend-docs]
requires:
  - phase: 01-codebase-hardening-quality-gates
    provides: Base codebase state with require_actor fallback and scaffold documentation
provides:
  - Production-safe actor resolution without admin fallback
  - Meaningful frontend-next/README.md describing the actual dashboard
  - Verified ARCHITECTURE.md correctly identifies active/legacy frontends
affects: [no downstream phases depend on this directly]
tech-stack:
  added: []
  patterns:
    - "require_actor() always raises HTTPException 400 when actor cannot be resolved"
key-files:
  created: []
  modified:
    - src/api/actor.py
    - frontend-next/README.md
    - docs/ARCHITECTURE.md (verified correct, no changes needed)
key-decisions:
  - "Removed unconditional 'admin' fallback — all missing-actor requests now return 400"
  - "Moved import os to top-level for consistency with module style"
requirements-completed: [Q-03, Q-04]
duration: 5min
completed: 2026-06-24
---

# Phase 01: Codebase Hardening — Plan 02 Summary

**Removed require_actor silent admin fallback in src/api/actor.py and replaced frontend-next/README.md with meaningful project documentation**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-24T...
- **Completed:** 2026-06-24T...
- **Tasks:** 2
- **Files modified:** 2 (1 code, 1 docs)

## Accomplishments

- Removed the `require_actor()` demo fallback that silently returned "admin" when no actor was provided outside test context — now all missing-actor requests correctly return HTTP 400
- Replaced the default Next.js `create-next-app` scaffold README with a meaningful project description covering pages, quick start, tech stack, code quality, and project structure
- Verified `docs/ARCHITECTURE.md` already correctly identifies `frontend-next/` as active and `frontend/` as legacy (no changes needed)
- Verified root `README.md` already correctly states `frontend-next/` is the active dashboard (no changes needed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix require_actor demo fallback** - `237a538` (fix)
2. **Task 2: Fix frontend-next/README.md and verify docs consistency** - `5645642` (docs)

## Files Created/Modified

- `src/api/actor.py` - Removed the `if not PYTEST_CURRENT_TEST: return "admin"` fallback; moved `import os` to top-level; always raises HTTPException 400 when actor cannot be resolved
- `frontend-next/README.md` - Replaced default create-next-app scaffold with meaningful project README describing the Adapter Dashboard (Next.js)

## Decisions Made

- `import os` moved to top-level imports for module style consistency (was inline inside function)
- No changes needed to `docs/ARCHITECTURE.md` or root `README.md` — both already correctly identified `frontend-next/` as the active frontend

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Auth hardening complete — `require_actor()` is now production-safe
- Documentation drift resolved — all docs consistently refer to `frontend-next/` as the active frontend
- Ready for next plans in the codebase hardening phase

---

## Self-Check: PASSED

- [x] `src/api/actor.py` — exists, no `return "admin"`, no `PYTEST_CURRENT_TEST`, has `raise HTTPException`
- [x] `frontend-next/README.md` — exists, no `create-next-app` scaffold, has `Adapter Dashboard` and `Legacy` section
- [x] `docs/ARCHITECTURE.md` — exists, has `Active Next.js` and `Legacy Vite`
- [x] Commit `237a538` — fix: remove require_actor silent admin fallback
- [x] Commit `5645642` — docs: replace frontend-next README and verify docs consistency
- [x] Commit `5645e29` — docs: complete plan 02 summary

*Phase: 01-codebase-hardening-quality-gates*
*Completed: 2026-06-24*
