---
phase: 260622-grp
plan: 01
subsystem: review-center
tags:
  - runtime-validation
  - migration
  - ui-enhancement
  - trace-gallery
dependency-graph:
  requires: []
  provides:
    - lib/review-runtime.ts (helpers)
    - types/review-center.ts (RuntimeFieldTrace, RuntimeTraceSample)
  affects:
    - guided-review-modal.tsx (Step 3)
    - review-center.module.css (new styles)
    - api/review-center.ts (traceSamples passthrough)
tech-stack:
  added:
    - Pure TS helper module (lib/review-runtime.ts) — 170 lines, 5 functions
  patterns:
    - traceSamples type-safe normalization with String/Number coercion
    - Inline overlay modal (no portal dependency)
    - CSS module dark-theme classes for progress bar, gallery, detail table
key-files:
  created:
    - frontend-next/src/lib/review-runtime.ts
  modified:
    - frontend-next/src/types/review-center.ts
    - frontend-next/src/lib/api/review-center.ts
    - frontend-next/src/components/review-center/guided-review-modal.tsx
    - frontend-next/src/components/review-center/review-center.module.css
decisions:
  - Use 🔍 emoji for trace detail button (zero icon library dependency)
  - Inline overlay for trace detail modal (separate position:fixed div, not portal)
  - Reuse existing Badge component for trace card status indicators
  - Insert new sections between existing ones (preserve layout per D-02)
metrics:
  duration: 18m
  completed-date: 2026-06-22
---

# Phase 260622-grp Plan 01: Migrate Review Runtime + Step 3 Enhancement Summary

Migrate 5 runtime helper functions from legacy `render.js` to a pure-TS `lib/review-runtime.ts`, add `RuntimeFieldTrace`/`RuntimeTraceSample` types, pass through `traceSamples` in API normalization, and enhance Step 3 of the guided review modal with a progress bar, before/after trace gallery, trace detail modal (7-column field-level table), and human-readable validation suggestions.

## Task Execution

### Task 1 — Create review-runtime lib + types + API passthrough ✓

| Action | Status | Files |
|--------|--------|-------|
| Add RuntimeFieldTrace + RuntimeTraceSample types | ✓ | types/review-center.ts |
| Add traceSamples to RuntimeValidationResult | ✓ | types/review-center.ts |
| Pass through normalized traceSamples in normalizeRuntimeValidation | ✓ | api/review-center.ts |
| Create lib/review-runtime.ts with 5 helpers + VALIDATION_SUGGESTIONS | ✓ | lib/review-runtime.ts |
| TypeScript compilation passes | ✓ | All 3 files clean |

**Commit:** `62c3f53`

### Task 2 — Enhance Step 3 with progress bar, trace gallery, trace detail modal ✓

| Action | Status | Files |
|--------|--------|-------|
| Add CSS classes (progress bar, gallery, modal, freshness) | ✓ | review-center.module.css |
| Wire imports + traceDetailSampleIndex state | ✓ | guided-review-modal.tsx |
| Add runtimeValidationState useMemo | ✓ | guided-review-modal.tsx |
| Insert progress bar + freshness section | ✓ | guided-review-modal.tsx |
| Insert trace gallery (before/after columns per sample) | ✓ | guided-review-modal.tsx |
| Insert trace detail modal overlay (7-column table) | ✓ | guided-review-modal.tsx |
| Add validation suggestions to issues list | ✓ | guided-review-modal.tsx |
| TypeScript compilation passes | ✓ | guided-review-modal.tsx |

**Commit:** `6a4822a`

## Deviations from Plan

None — plan executed exactly as written.

## Key Design Decisions

1. **Emoji icon for trace detail button** (`🔍`) — zero dependency on icon libraries, same pattern used in legacy UI for simplicity
2. **Inline overlay modal** — uses a `position: fixed` div with `z-index: 100` instead of a portal/dialog to avoid nesting conflicts within the existing Dialog component
3. **Reuses existing Badge component** — trace card status labels (`Passed`/`Warning`/`Failed`) use the same `<Badge severity={...}>` pattern as the validation banner
4. **Section insertion preserves existing layout** — per D-02, all new sections are inserted between existing sections (metrics → progress bar → field results → trace gallery → preview rows → issues + suggestions → detail overlay)

## Verification

- ✅ `npx tsc --noEmit --strict` passes for all 5 modified/created files
- ✅ `lib/review-runtime.ts` — 170 lines (exceeds 120 minimum)
- ✅ `types/review-center.ts` has `RuntimeFieldTrace`, `RuntimeTraceSample`, `traceSamples` on `RuntimeValidationResult`
- ✅ `lib/api/review-center.ts` passes through normalized `traceSamples`
- ✅ Step 3 renders: progress bar (green/red segments + legend), freshness section (badge + version), trace gallery (before/after columns per sample), trace detail modal (7-column field-level table on 🔍 click), and suggestions beneath each issue message

## Self-Check: PASSED

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced.
