---
phase: 19
plan: 01
subsystem: frontend
tags: [review-center, actions]
key-files:
  created: []
  modified: []
metrics:
  commits: 0
  files_changed: 0
---

## Plan 19-01: Review Center — Full Workflow

### Verification

All 5 actions (validate, approve-activate, approve-keep-current, reject, send-to-studio) were already implemented and wired to their backend endpoints. Scope override selector is present. User-facing UI already uses "Review Center" (Phase 17). Remaining "review_queue" references are backward-compat aliases and internal keys.

### Self-Check: PASSED

- No user-facing "Review Queue" text remains in rendered UI
- All 5 actions call correct backend endpoints
- Scope override wired in frontend
