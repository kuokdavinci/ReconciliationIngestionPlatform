# ROADMAP — Reconciliation Ingestion Platform

**Last Updated:** 2026-06-24
**Status:** Active development

---

## Overview

Config-driven platform for ingesting partner settlement files, normalizing into canonical transactions, matching against internal records via deterministic reconciliation, and managing mapping changes through human-in-the-loop approval workflows.

---

## Milestones

### M1: Production-Ready Foundation

**Goal:** Stabilize the codebase for production-grade operation. Fix quality gates, expand CI coverage, resolve docs drift, refactor god entrypoint, and establish proper security patterns.

#### Phase 1: Codebase Hardening & Quality Gates

**Goal:** Fix the 6 critical quality issues preventing production-readiness — tightening lint/type gates, expanding CI coverage, hardening auth, resolving docs drift, decomposing the god entrypoint, and establishing proper migration tooling.

**Status:** ✅ Planned (4 plans, 2 waves)

**Requirements:**
- `Q-01` — Tighten Python quality gates (Ruff strict mode + mypy per-module) → Plan 01
- `Q-02` — Expand CI to run full test suite (API, ingestion, reconciliation) → Plan 01
- `Q-03` — Fix auth/security demo-level patterns (require_actor fallback) → Plan 02
- `Q-04` — Resolve docs drift between README, ARCHITECTURE.md, and frontend-next/README → Plan 02
- `Q-05` — Decompose run.py god entrypoint into modular CLI scripts → Plan 03
- `Q-06` — Replace Base.metadata.create_all with Alembic migration system → Plan 04

**Plans:** 4 plans in 2 waves

| Wave | Plans | Requirements |
|------|-------|-------------|
| 1    | 01, 02, 03 | Q-01, Q-02, Q-03, Q-04, Q-05 |
| 2    | 04        | Q-06 |

Plans:
- [x] 01-01-PLAN.md — Quality gates + CI expansion (Q-01, Q-02)
- [x] 01-02-PLAN.md — Auth hardening + docs drift fix (Q-03, Q-04)
- [x] 01-03-PLAN.md — run.py decomposition (Q-05)
- [x] 01-04-PLAN.md — Alembic migration setup (Q-06, depends on Plan 01)

---

## Future Phases (Backlog)

### Phase 2: Frontend Quality & Testing
- Frontend test setup
- Error boundaries
- Request retry + cancellation
- TypeScript strict mode

### Phase 3: MongoDB → PostgreSQL Migration Completion
- Complete PostgreSQL migration
- Remove MongoDB dependencies
- Remove mongo-express
- Remove hybrid repo patterns

### Phase 4: Production Security Hardening
- RBAC system
- Session management
- Audit trail completion
- SFTP host key verification

---

## Completed

| Phase | Status | Plans | Completion |
|-------|--------|-------|------------|
| — | ✓ | — | Quick task: Batch Size & Parallel Execution Optimization (2026-06-23) |

---

## Document Contract

This roadmap is the source of truth for all phase planning. Each phase entry must have:
- Clear goal statement
- Requirement IDs (Q-NN format for quality, F-NN for features, S-NN for security)
- Plan list with completion status
- Dependency references to prior phases

---

*ROADMAP generated: 2026-06-24*
