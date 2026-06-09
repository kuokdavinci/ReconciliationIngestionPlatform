# UX Refactor — Phases 17–20

## Product Goal

Turn the UI into a simple reconciliation operations flow. The admin manages post-reconciliation operations with AI/Copilot **support**, not as a complex control tower.

## Core Principles

- **Dashboard** shows operational status — no more.
- **Copilot** explains and supports decisions — does not execute.
- **Review Center** handles approvals — the full workspace.
- **Mapping Studio** fixes mapping — a tool, not a primary nav item.
- **Reconciliation** shows results + AI insights.

## Navigation

```
Primary:
  Data Intake
  Review Center
  Reconciliation
  Automation

Tools (secondary group):
  Mapping Studio
```

## Phase Breakdown

| # | Focus | Plans | Effort |
|---|-------|-------|--------|
| **17** | Navigation restructure + Data Intake refactor | 3 plans | ~450 lines frontend + backend |
| **18** | Copilot Brief 3-step modal (Brief → Review → Decision) | 3 plans | ~350 lines frontend + backend |
| **19** | Review Center rename + Mapping Studio workspace | 3 plans | ~500 lines frontend + backend |
| **20** | Reconciliation view + contextual Copilot roles | 3 plans | ~300 lines frontend + backend |

## Key Decisions

- Mapping Studio moves to a "Tools" sub-group in nav, not a primary step.
- Review Queue → Review Center.
- Copilot Brief is exactly 3 steps; approve/reject only on Decision step.
- Dashboard shows only facts (runtime, latest file, review count).
- Mapping Studio ↔ Review Center handoff is bidirectional.
- After Approve & activate, reconciliation runs automatically.
- Copilot is contextualized per screen (Intake triage, Review analyst, Reconciliation analyst, Automation helper).

## Coverage

| Acceptance Criterion | Phase | Plan |
|---|---|---|
| Navigation: Data Intake, Review Center, Reconciliation, Automation as primary | 17 | 1 |
| Mapping Studio under Tools group | 17 | 1 |
| Data Intake — Partner Snapshot grid | 17 | 2 |
| Data Intake — Selected Partner Summary card | 17 | 2 |
| Copilot Brief — Step 1: Brief (3-second overview) | 18 | 2 |
| Copilot Brief — Step 2: Review (inline Review summary) | 18 | 2 |
| Copilot Brief — Step 3: Decision (approve/reject/keep) | 18 | 2+3 |
| Review Center rename + full workflow | 19 | 1 |
| Mapping Studio workspace (upload, AI, validate, handoff) | 19 | 2 |
| Handoff integration (Mapping Studio → Review Center) | 19 | 3 |
| Reconciliation tabs + filters + AI Insights | 20 | 1 |
| Contextual Copilot per screen | 20 | 2 |
| Auto-trigger reconciliation after approval | 20 | 3 |
| Only one dominant CTA per step in brief | 18 | 2 |
| No repeated buttons across dashboard and brief | 18 | 2+3 |
| Dashboard refresh + toast after approve/reject | 18 | 3 |

## Files Affected

| File | Phase(s) |
|---|---|
| `frontend/app.js` — routes, nav, render functions | 17, 18, 19, 20 |
| `frontend/styles.css` — new component styles | 17, 18, 19, 20 |
| `src/copilot/context.py` — 3-step context endpoint | 18 |
| `src/api/operations.py` — intake API | 17 |
| `src/api/review_packets.py` — review API | 19 |
| `src/api/mappings.py` — mapping API | 19 |
| `src/api/reconciliation.py` — reconciliation API | 20 |
| `src/scheduler/reconciliation.py` — auto-trigger | 20 |
