# Scheduler Status Layout Redesign

## Design read

This is a B2B operator dashboard for monitoring scheduler and ingestion checkpoints. The interface should feel data-dense but scannable, with stable row geometry and a single accent/status language.

## Problem

The scheduler table currently renders runtime badges, recovery status, status text, progress, current unit, last checkpoint, attempts, retry timing, error code, pending count, and multiple actions in the same row. Long checkpoint values and several simultaneous statuses make the actions column overflow or become difficult to use.

## Goals

- Keep each scheduler row compact and stable when recovery data is populated.
- Preserve quick visibility of runtime state, recovery severity, and progress.
- Keep `View recovery` as the single entry point for complete checkpoint and event details.
- Keep `Run Now` and recovery actions usable without wrapping or horizontal collision.
- Preserve existing API contracts, recovery behavior, filters, polling, and drawer interactions.
- Improve responsive behavior and accessible labels.

## Non-goals

- No backend or API changes.
- No changes to checkpoint semantics, polling behavior, or recovery permissions.
- No redesign of recent automation output or unrelated dashboard sections.

## Layout

The scheduler table keeps its existing six-column structure:

1. Partner
2. Method
3. Schedule
4. Destination
5. Runtime State
6. Actions

The Runtime State cell becomes a fixed-priority summary:

- Row 1: enabled/disabled badge and runtime badge.
- Row 2: short recovery badge when recovery is not `IDLE`.
- Row 3: progress (`completed/total units`) and current unit when available.
- Row 4: one priority detail selected by state: error code for failures, next retry for retryable states, or last completed unit for completed states.

The full `currentUnit`, `lastCompletedUnit`, cursor, attempts, error, events, and operator controls remain in `RecoveryDetailsPanel`.

The Actions cell contains at most `View recovery` and `Run Now`. Pending review count is rendered as compact secondary metadata and does not compete with the primary buttons.

## Responsive behavior

- Desktop uses a fixed minimum width for the status summary and a non-wrapping action group.
- Long unit keys and error codes use ellipsis or safe word breaking inside the status summary.
- Narrow layouts may scroll the table horizontally; buttons must remain visible and must not wrap their labels.
- At the mobile/tablet breakpoint, low-priority method/schedule/destination metadata may be grouped under partner metadata while runtime/recovery and actions remain prominent.
- `min-width: 0` is applied to grid/flex children that contain dynamic text.

## Component structure

- Add a focused `ScheduleRecoverySummary` component for priority selection and summary markup.
- Keep `ScheduleTable` responsible for table structure, partner metadata, and actions.
- Keep `RecoveryDetailsPanel` as the detailed recovery read/write surface.
- Add scoped CSS for summary line clamping, action layout, long-value handling, and responsive breakpoints.

## Accessibility and interaction

- Summary markup exposes a complete `aria-label` even when visible text is truncated.
- Existing drawer focus trap, Escape handling, and focus restoration remain intact.
- Action labels remain short, single-line, and distinguishable.
- Status colors continue to be paired with readable text, not used as the only signal.

## Verification

- Add E2E coverage for `FAILED`, `BLOCKED`, and `WAITING_REVIEW` rows with long checkpoint/error values.
- Assert the action buttons remain visible and clickable.
- Assert opening the drawer still exposes complete checkpoint details.
- Run frontend typecheck, lint, Webpack production build, and the complete E2E suite.

