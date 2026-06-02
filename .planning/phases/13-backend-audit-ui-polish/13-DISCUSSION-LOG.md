# Phase 13: Backend Audit & UI Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 13-backend-audit-ui-polish
**Areas discussed:** Backend audit scope, Data flow guard, UI mapping dashboard, UI core feature widgets

---

## Backend Audit Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All components | Ingestion, normalizer, validator, reconciliation engine, AI analysis — end-to-end | ✓ |
| Reconciliation + Data Flow only | Focus on reconciliation engine correctness and data flow | |
| Custom scope | User specifies which components | |

**User's choice:** All components
**Notes:** Edge case focus: empty files, missing fields, duplicate traces, amount mismatches, status mapping gaps. Verify existing tests cover these.

## Data Flow Guard

| Option | Description | Selected |
|--------|-------------|----------|
| Add guard in reconciliation engine | Pre-check in ReconciliationEngine that skips unmapped records | ✓ |
| Audit normalizer only | Verify normalizer already handles it | |
| Both | Audit normalizer coverage AND add guard | |

**User's choice:** Add guard in reconciliation engine
**Notes:** Unmapped records are skipped with a structured warning log entry. Reconciliation stats include skipped count.

## UI Mapping Dashboard

| Option | Description | Selected |
|--------|-------------|----------|
| Active configs + field mappings | Show config per partner with field mapping rules | ✓ |
| Full mapping management | Configs + ability to create/edit from UI | |
| Minimal config list | Simple table with partner, version, last used | |

**User's choice:** Active configs + field mappings
**Notes:** New sidebar tab "Mapping Configs" between Reconciliation and AI Insights. New `GET /api/v1/mappings` endpoint. Full API endpoint + UI approach.

## UI Core Feature Widgets

| Option | Description | Selected |
|--------|-------------|----------|
| Reconciliation health widget | Healthy/anomaly status per partner, last reconciliation timestamp, pending items | ✓ |
| Recent mismatches list | Small table of recent mismatches | |
| Operating status overview | Pipeline health, files today, active schedulers | |
| Combined | All of the above | |

**User's choice:** Reconciliation health widget
**Notes:** Added to Overview dashboard. Fetches data from existing `/api/v1/reconciliation/stats` endpoint.

## OpenCode's Discretion

- Test implementation details (pytest, follow existing patterns)
- UI component styling (Material Symbols + existing CSS patterns)
- Reconciliation health widget visual design

## Deferred Ideas

- AI-powered mapping config suggestion from partner data (future phase)
