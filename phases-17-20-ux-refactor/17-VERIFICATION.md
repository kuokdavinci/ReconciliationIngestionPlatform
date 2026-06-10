---
phase: 17-navigation-restructure-data-intake-refactor
verified: 2026-06-09T15:45:00Z
status: gaps_found
score: 5/5 must-haves verified (with 2 minor gaps in non-rendered backend code)
overrides_applied: 0
gaps:
  - truth: 'No stale "Review Queue" references exist anywhere in the codebase'
    status: partial
    reason: >
      User-facing UI (nav, routes, subtitles, toasts, action buttons) is completely clean.
      However, 3 non-rendered code paths still contain "Review Queue" text:
      (1) src/api/operations.py _compute_partner_state() nextAction strings,
      (2) src/services/copilot_context.py button label,
      (3) frontend/README.md documentation.
      Neither (1) nor (2) is rendered in the frontend UI.
    artifacts:
      - path: src/api/operations.py
        issue: 'Lines 59, 61: nextAction text contains "Review Queue" (not rendered in frontend)'
      - path: src/services/copilot_context.py
        issue: 'Line 364: button label "Open Review Queue" (frontend ignores backend label, maps from action key instead)'
      - path: frontend/README.md
        issue: "9 references to Review Queue (documentation file)"
    missing:
      - Update nextAction strings in operations.py _compute_partner_state to use "Review Center"
      - Update copilot_context.py button label to "Open Review Center"
      - Update frontend/README.md documentation references
---

# Phase 17: Navigation Restructure + Data Intake Refactor — Verification Report

**Phase Goal:** Restructure sidebar navigation (Mapping Studio → Tools sub-group, Review Queue → Review Center). Rewrite Data Intake landing with Partner Snapshot grid + minimal Selected Partner Summary card.

**Verified:** 2026-06-09T15:45:00Z
**Status:** gaps_found (minor — non-user-visible stale references)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Navigation has 4 primary items + Tools sub-group with Mapping Studio | ✓ VERIFIED | `routes` array (app.js:38-43): Data Intake, Review Center, Reconciliation, Automation. `utilityRoutes` (app.js:44-46): mapping-studio. `renderNav()` (app.js:251-271): renders `.nav-divider` + `.nav-subgroup-label` + Mapping Studio in Tools. `.nav-subgroup-label` CSS (styles.css:177) present. |
| 2 | Review Queue → Review Center rename in all user-facing UI | ✓ VERIFIED | Nav label "Review Center" (app.js:40). Route alias `review-queue → review-center` (app.js:331). Subtitle "Review pending runtime changes" (app.js:359). Action handler `go-review-center` (app.js:2743). Backward-compat aliases preserved. |
| 3 | Data Intake — Partner Snapshot grid + Selected Partner Summary with 3 fact pills | ✓ VERIFIED | `renderPartnerIntake()` (app.js:516-602) renders `.intake-partner-grid` with per-partner cards showing name/state/badges. `.intake-dashboard-card` (app.js:572-598) shows 3 fact pills (Runtime, Latest file, Review), copilot line, Open Brief, Upload file. CSS classes exist (styles.css:2077-2216). |
| 4 | No evidence cards, safe checks, or decision controls on intake dashboard | ✓ VERIFIED | `renderPartnerIntake()` contains no evidence/safeChecks/decisionControls rendering. Only `renderCopilotBrief()` (a separate modal overlay) references those — not inline on dashboard. Old CSS classes (`intake-copilot-layout`, `intake-compact-row`, `intake-mini-indicators`, `copilot-summary-card`) confirmed removed from styles.css. |
| 5 | Backend returns draftMappingId/reviewItemId fields instead of proposalConfigId/reviewPacketId | ✓ VERIFIED | Frontend uses `draftMappingId`/`reviewItemId` throughout (33 matches in app.js). Backend models use `AliasChoices("draftMappingId", "proposalConfigId")` for backward compat. API response in `operations.py` returns `draftMappingId`/`reviewItemId`. Tests verify old names NOT in rendered output (test_api_copilot.py:126-127). No `proposalConfigId`/`reviewPacketId` in frontend/. |

**Score:** 5/5 truths verified

### Deferred Items

No items are deferred — all must-haves have implementation evidence in this phase.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/app.js` (routes/nav) | 4 primary + Tools subgroup | ✓ VERIFIED | Lines 38-46: routes and utilityRoutes defined correctly |
| `frontend/app.js` (renderNav) | Tools sub-group rendering | ✓ VERIFIED | Lines 251-271: renders nav-divider + nav-subgroup-label + utility buttons |
| `frontend/app.js` (onRouteChange) | Route aliases + hash handling | ✓ VERIFIED | Lines 324-347: aliases include review-queue → review-center |
| `frontend/app.js` (renderPartnerIntake) | Snapshot grid + Summary card | ✓ VERIFIED | Lines 516-602: full implementation |
| `frontend/styles.css` (nav classes) | .nav-subgroup-label | ✓ VERIFIED | Line 177: present |
| `frontend/styles.css` (dashboard) | .intake-dashboard-card, .intake-dash-facts, .intake-dash-copilot | ✓ VERIFIED | Lines 2141, 2161, 2199: all present |
| `frontend/styles.css` (removed) | Old classes purged | ✓ VERIFIED | No matches for intake-copilot-layout, intake-compact-row, intake-mini-indicators, copilot-summary-card |
| `src/api/operations.py` | Intake endpoint with required fields | ✓ VERIFIED | Lines 115-264: returns partners[], detail.statusHeader, pendingItems, all required fields |
| `src/api/operations.py` (fields) | draftMappingId, reviewItemId | ✓ VERIFIED | Lines 207-208: returns draftMappingId/reviewItemId in pendingItems |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| renderPartnerIntake | `/api/v1/operations/intake` | fetchJson | ✓ WIRED | app.js:401-402: fetches intake API with partner+date params |
| renderPartnerIntake | `/api/v1/copilot/context` | fetchJson | ✓ WIRED | app.js:402-403: fetches copilot context API |
| renderNav | Routes/utility arrays | template loop | ✓ WIRED | app.js:252-264: maps routes to nav buttons |
| Nav buttons | Route change | click → hashchange | ✓ WIRED | app.js:266-270: onclick sets location.hash |
| Route aliases | Canonical routes | onRouteChange | ✓ WIRED | app.js:326-334: review-queue → review-center mapping |
| Selection click | State update + re-render | data-action select-partner | ✓ WIRED | app.js:2729-2735: updates state.partner, calls render() |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| Partner Snapshot grid | `data.partners` | `/api/v1/operations/intake` → `_compute_partner_state()` queries DB | DB queries via mapping/action/file/packet repos | ✓ FLOWING |
| Summary card facts | `detail.currentRuntimeConfigSummary`, `detail.latestFileSummary`, `detail.pendingItems` | Same intake API | DB-queried per partner | ✓ FLOWING |
| Copilot sentence | `copilot.status` | `/api/v1/copilot/context` | Backend context endpoint | ✓ FLOWING |

### Behavioral Spot-Checks

**Step 7b: SKIPPED** — no runnable API server is running; verification is based on static code analysis.

### Requirements Coverage

| Requirement | Source | Description | Status | Evidence |
|-------------|--------|-------------|--------|----------|
| UX-NAV-01 | ROADMAP.md | Reorder primary nav + add Tools sub-group with Mapping Studio | ✓ SATISFIED | routes array (app.js:38-43), utilityRoutes (app.js:44-46), renderNav() (app.js:251-271) |
| UX-NAV-02 | ROADMAP.md | Rename "Review Queue" → "Review Center" everywhere | ✗ PARTIAL | UI is clean (nav, routes, subtitles, toasts); 3 stale references in non-rendered code paths (see gaps) |
| UX-INTAKE-07 | ROADMAP.md | Partner Snapshot grid — partner name, overall status, latest file, file count, pending changes | ✓ SATISFIED | renderPartnerIntake() (app.js:524-543): grid of intake-partner-card elements with all fields |
| UX-INTAKE-08 | ROADMAP.md | Selected Partner Summary — 3 fact pills, copilot sentence, Open Brief, Upload file | ✓ SATISFIED | renderPartnerIntake() (app.js:572-598): intake-dashboard-card with all required elements |
| UX-INTAKE-09 | ROADMAP.md | Remove evidence cards, safe checks, decision controls from dashboard | ✓ SATISFIED | renderPartnerIntake() has no evidence/safeChecks/decisionControls. Old CSS classes purged. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/api/operations.py | 59, 61 | Stale "Review Queue" text in nextAction strings | ℹ️ Info | Not rendered in frontend UI (nextAction unused by app.js) |
| src/services/copilot_context.py | 364 | Stale "Open Review Queue" button label | ℹ️ Info | Not displayed — frontend maps from action key, not backend label |
| frontend/README.md | 11, 43-53, 56 | 9 references to "Review Queue" | ℹ️ Info | Documentation file; not user-facing UI |
| frontend/app.js | 604-638 | `renderCopilotSummaryCard()` function exists but is unused | ℹ️ Info | Dead code — not called by any render function. Could be cleaned up. |

### Stub Classification

No stubs found. All artifacts checked at levels 1-4:

- `renderPartnerIntake()` (Level 1: exists, Level 2: 45+ substantive lines of grid/dashboard rendering, Level 3: wired to API, Level 4: data flows from DB queries)
- `renderNav()` (Level 1: exists, Level 2: full nav rendering with subgroup, Level 3: wired to click handlers)
- `onRouteChange()` (Level 1: exists, Level 2: proper routing with aliases, Level 3: calls render with correct state)
- Backend `operations.py` (Level 1: exists, Level 2: full API with partners/detail queries, Level 3: connects to DB repositories)

### Human Verification Required

None. All checks can be verified through static code analysis. The visual appearance (card layout, spacing, colors) is handled by the CSS classes which have been verified present.

### Gaps Summary

**1 minor gap found — stale "Review Queue" references (non-rendered code paths):**

The user-facing UI is fully clean — navigation shows "Review Center", route aliases redirect old hashes, subtitles and action buttons all use "Review Center". However, three non-rendered code paths still contain "Review Queue":

1. **`src/api/operations.py` (lines 59, 61):** `_compute_partner_state()` returns `nextAction` strings like "Create or review a draft mapping in Review Queue". The frontend does NOT render `nextAction` — it only uses `primaryReason`. These strings are effectively dead data.

2. **`src/services/copilot_context.py` (line 364):** Primary action button has `"label": "Open Review Queue"`. The frontend ignores the backend's label field and maps from the action key (`"review_proposal"` → `"Open Review Center"` via `actionLabel()` in app.js:734). So this label is never displayed.

3. **`frontend/README.md` (9 references):** Documentation file describing routes and API endpoints. Not part of the active UI but should be updated for consistency.

**Recommendation:** Fix in a follow-up or during phase 18/19 cleanup. None of these break user-facing behavior.

Additionally, `renderCopilotSummaryCard()` function (app.js:604-638) remains as dead code — it's defined but never called by any render function. This is cosmetic and does not affect goal achievement.

---

_Verified: 2026-06-09T15:45:00Z_
_Verifier: OpenCode (gsd-verifier)_
