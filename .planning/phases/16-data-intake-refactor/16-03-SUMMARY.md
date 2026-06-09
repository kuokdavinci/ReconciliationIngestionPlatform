---
phase: 16-data-intake-refactor
plan: 03
subsystem: ui
tags: [copilot, panel, compact, decision-card, expand-collapse]
requires:
  - phase: 16-data-intake-refactor
    plan: 01
    provides: Compact decision-mode fields (primaryAction, secondaryActions, summary, reasons)
provides:
  - Compact Copilot Panel with collapsed evidence/safe-checks sections
affects: [data-intake screen]

tech-stack:
  added: []
  patterns:
    - "Decision state → primary action rendering via backend primaryAction field"
    - "Collapsible evidence/safe-checks using native <details>/<summary> elements"

key-files:
  created: []
  modified:
    - frontend/app.js
    - frontend/styles.css

key-decisions:
  - "Evidence details and safe checks rendered using native HTML <details> elements (no JS toggle needed)"
  - "Loading state heading changed from 'Copilot Panel' to 'Copilot' to match compact design"

requirements-completed:
  - UI-INTAKE-03
  - UI-INTAKE-04
  - UI-INTAKE-05
  - UI-INTAKE-06

duration: 1min
completed: 2026-06-09
---

# Phase 16 Data Intake Refactor — Plan 03 Summary

**Compact Copilot Panel with decision state → primary action mapping; evidence and safe checks hidden behind expand/collapse toggles**

## Performance

- **Duration:** 19s
- **Started:** 2026-06-09T06:35:11Z
- **Completed:** 2026-06-09T06:35:30Z
- **Tasks:** 2 (of 2)
- **Files modified:** 2

## Accomplishments

- **Task 1: Rewrote `renderCopilotPanel()` to compact decision mode**
  - Shows status badge, risk level badge, headline, summary, 2-3 reasons list, and one primary action button
  - Uses `copilot.summary` (new compact one-liner) instead of full `explanation` array
  - Uses `copilot.reasons` (2-3 items) instead of full explanation
  - Uses `copilot.primaryAction` and `copilot.secondaryActions` directly from backend
  - Evidence section wrapped in `<details>` with "Evidence details" summary — collapsed by default
  - Safe checks section wrapped in `<details>` with "Safe checks" summary — collapsed by default
  - Removed "Why" and "Actions" section headers — actions inline, reasons as bullet list
  - Added CSS classes: `copilot-compact`, `copilot-header-compact`, `copilot-collapsed`, `copilot-summary`, `copilot-reasons`, `copilot-primary-action`
  - Verified no `proposalConfigId` or `targetConfigId` leaks in rendered output

- **Task 2: Added CSS for compact Copilot Panel collapsed sections**
  - Styled `.copilot-compact` with min-width constraint
  - Styled `.copilot-header-compact` with flex layout, gap, and compact `h2` (16px/700 weight)
  - Styled `.copilot-summary` with 13px muted text
  - Styled `.copilot-reasons` as bullet list with `::before` pseudo-element
  - Styled `.copilot-actions` as flex wrap container
  - Styled `.copilot-primary-action` as flex-fill button (min-width 160px)
  - Styled `.copilot-collapsed` details with top border, hover effect, rotate animation on expand_more icon
  - Styled `.copilot-collapsed .copilot-evidence-grid` as 3-column grid with compact labels/text
  - No existing CSS classes were modified

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite renderCopilotPanel to compact decision mode** — `f2f2ba5` (feat)
2. **Task 2: Add CSS for compact Copilot Panel collapsed sections** — `fe09051` (style)

## Files Created/Modified

- `frontend/app.js` — Rewrote `renderCopilotPanel()`: compact decision card with collapsed evidence/safe-checks, new field consumption (summary, reasons, primaryAction, secondaryActions)
- `frontend/styles.css` — Added 125 lines of new CSS for compact panel layout, collapsed sections, evidence grid, reasons list, primary action button styling

## Decisions Made

- **Native `<details>` elements used for collapsible sections:** No JavaScript toggle logic needed — the browser's native `<details>`/`<summary>` handles open/close state and provides keyboard accessibility by default. The `expand_more` icon rotates 90deg when `[open]`.
- **Loading state heading changed from "Copilot Panel" to "Copilot":** Matches the compact design philosophy — the old header had redundant "Panel" suffix and unnecessarily wide "Copilot Panel" title.

## Deviations from Plan

None — plan executed exactly as written.

## Autofix Attempts

None — no build/test step applies to static frontend files; no autofix cycles were needed.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Copilot Panel now renders compact decision card with all D-05 fields
- Evidence and safe checks hidden behind expand/collapse toggles
- Each decision state shows correct primary action per backend mapping
- All legacy field names removed from rendered output
- No blockers

## Self-Check: PASSED

- ✓ frontend/app.js exists (3653 lines)
- ✓ frontend/styles.css exists (2732 lines)
- ✓ 16-03-SUMMARY.md exists
- ✓ f2f2ba5 (Task 1 commit) found
- ✓ fe09051 (Task 2 commit) found
- ✓ copilot-compact class in app.js
- ✓ copilot-collapsed class in app.js (evidence + safe checks)
- ✓ Evidence details in `<details>` element (collapsed by default)
- ✓ Safe checks in `<details>` element (collapsed by default)
- ✓ No legacy field leaks (no proposalConfigId/targetConfigId in output)
- ✓ copilot-compact CSS in styles.css
- ✓ copilot-collapsed-summary CSS in styles.css

---

*Phase: 16-data-intake-refactor*
*Completed: 2026-06-09*
