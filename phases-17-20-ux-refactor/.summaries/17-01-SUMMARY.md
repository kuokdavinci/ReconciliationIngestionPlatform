---
phase: 17
plan: 01
subsystem: frontend
tags: [nav, sidebar, routes]
key-files:
  created: []
  modified:
    - frontend/app.js
    - frontend/styles.css
metrics:
  commits: 1
  files_changed: 2
---

## Plan 17-01: Navigation Restructure

### Tasks Executed

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Reorder primary nav: Data Intake, Review Center, Reconciliation, Automation | ✓ | f422e71 |
| 2 | Add Tools sub-group in sidebar with Mapping Studio | ✓ | f422e71 |
| 3 | Rename Review Queue → Review Center in nav, routes, subtitles, toasts | ✓ | f422e71 |
| 4 | Update route mappings, aliases, hash-change handling | ✓ | f422e71 |
| 5 | Add `.nav-subgroup-label` CSS for Tools group | ✓ | f422e71 |

### Deviations

None.

### Self-Check: PASSED

- Routes array: 4 primary + 1 utility (mapping-studio in Tools)
- renderNav() shows Tools sub-group label
- All "Review Queue" → "Review Center" in user-facing UI
- Route aliases include backward-compat `review-queue` → `review-center`
- JS bracket balance OK; CSS class names consistent
