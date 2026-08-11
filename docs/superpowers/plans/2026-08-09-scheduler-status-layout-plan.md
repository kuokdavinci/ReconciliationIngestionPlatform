# Scheduler Status Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep scheduler rows compact and actionable by replacing the overloaded checkpoint status block with a fixed-priority summary and responsive action layout.

**Architecture:** Add a focused `ScheduleRecoverySummary` presentation component. Keep `ScheduleTable` responsible for table structure and actions, and keep `RecoveryDetailsPanel` as the complete checkpoint detail surface. Use scoped CSS and E2E regression coverage without changing API contracts or recovery behavior.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, CSS Modules, Playwright.

## Global Constraints

- No backend or API changes.
- Preserve existing recovery behavior, filters, polling, and drawer interactions.
- Keep status colors paired with readable text; color is not the only status signal.
- Buttons must remain single-line and usable at desktop and narrow widths.
- Run frontend typecheck, lint, Webpack production build, and complete E2E suite.

---

### Task 1: Add a failing overflow regression test

**Files:**
- Modify: `frontend-next/e2e/dashboard-interactions.spec.ts`

**Interfaces:**
- Consumes: Existing mocked `/api/v1/automation/jobs` response and scheduler route.
- Produces: A browser regression that proves long checkpoint values do not hide or push action buttons out of the row.

- [ ] **Step 1: Extend the failed-recovery fixture with long values**

In the existing `operator can recover a failed ViettelPay page from the schedules view` test, use long but realistic values for `currentUnitKey`, `lastCompletedUnitKey`, `streamKey`, `errorCode`, and `lastError`. Keep the recovery actions and drawer assertions unchanged.

- [ ] **Step 2: Add action visibility and single-line assertions**

After the row is loaded, add assertions equivalent to:

```ts
const actions = row.locator("td").last();
await expect(actions.getByRole("button", { name: "View recovery", exact: true })).toBeVisible();
await expect(actions.getByRole("button", { name: "Run Now", exact: true })).toBeVisible();
await expect(actions.getByRole("button", { name: "Run Now", exact: true })).toHaveCSS("white-space", "nowrap");
```

Also assert that the visible table summary contains the compact progress/error information, while the long raw value is available after opening the drawer.

- [ ] **Step 3: Run the focused test and verify it fails for the current layout**

Run:

```bash
PLAYWRIGHT_PORT=3101 npm run test:e2e -- --grep "recover a failed ViettelPay page"
```

Expected: the test reaches the scheduler row but fails on the new compact-summary/action geometry assertion or exposes the current overloaded row behavior. Do not change production code in this step.

### Task 2: Create the compact recovery summary component

**Files:**
- Create: `frontend-next/src/components/schedules/schedule-recovery-summary.tsx`
- Modify: `frontend-next/src/components/schedules/schedules.module.css`

**Interfaces:**
- Consumes: `ScheduleJob` from `@/types/schedules` and the existing status helpers from `./recovery-status`.
- Produces: `ScheduleRecoverySummary({ job }: { job: ScheduleJob })`, which renders the compact runtime/recovery summary and a complete accessible label.

- [ ] **Step 1: Write the component contract and priority selection**

Implement a pure presentation component with this priority behavior:

```ts
interface Props {
  job: ScheduleJob;
}
```

Render enabled state and runtime state first. If recovery is not `IDLE`, render the recovery label. Render progress only when `totalUnitCount > 0`, appending the current unit as secondary text when present. Render exactly one priority detail:

- `FAILED` or `BLOCKED`: `errorCode` or `lastError`.
- retryable state with `nextRetryAt`: the existing `RecoveryCountdown`.
- otherwise: `lastCompletedUnitKey` when available.

Do not render the previous full set of `current`, `checkpoint`, `attempt`, `next`, and `error` lines in the table.

- [ ] **Step 2: Add accessible summary markup**

Give the summary root an `aria-label` containing partner, runtime status, recovery status, progress, and the selected priority detail. Use the visible compact labels for sighted users and preserve long values in the aria label or truncated element `title`.

- [ ] **Step 3: Add scoped CSS for stable geometry**

Add CSS classes for a summary grid with `min-width: 0`, bounded detail lines, `overflow: hidden`, `text-overflow: ellipsis`, and safe wrapping for error/unit values. Keep the summary visually compact and avoid adding a new card layer inside every table cell.

### Task 3: Simplify `ScheduleTable` and make actions responsive

**Files:**
- Modify: `frontend-next/src/components/schedules/schedule-table.tsx`
- Modify: `frontend-next/src/components/schedules/schedules.module.css`

**Interfaces:**
- Consumes: `ScheduleRecoverySummary` from Task 2.
- Produces: A six-column table whose status cell delegates summary rendering and whose actions remain visible and clickable.

- [ ] **Step 1: Replace the overloaded status markup**

Replace the existing `statusCell`, `statusBadges`, `statusText`, `recoverySummary`, `recoveryLine`, and `recoveryError` markup in `ScheduleTable` with:

```tsx
<td className={`${styles.cell} ${styles.statusCell}`}>
  <ScheduleRecoverySummary job={job} />
</td>
```

Keep `onViewRecovery`, `Run Now`, and pending count in the actions cell.

- [ ] **Step 2: Separate primary actions from secondary pending metadata**

Render pending count in a compact metadata element above or beside a primary action group. The primary action group must use `flex-wrap: nowrap`, `white-space: nowrap`, and `min-width: max-content` for buttons. At the narrow breakpoint, switch the action group to a vertical layout rather than allowing button text to wrap.

- [ ] **Step 3: Add table-cell width and responsive rules**

Apply `min-width: 0` to the status cell and its children. Give the status column a practical minimum width, keep the table wrapper horizontally scrollable, and add a mobile/tablet media query that preserves Partner, Runtime State, and Actions prominence while allowing low-priority metadata to wrap or group.

- [ ] **Step 4: Run the focused E2E test and verify it passes**

Run:

```bash
PLAYWRIGHT_PORT=3101 npm run test:e2e -- --grep "recover a failed ViettelPay page"
```

Expected: PASS, with long checkpoint/error values visible through the drawer and both row actions still visible.

### Task 4: Verify all scheduler states and full frontend quality gates

**Files:**
- Modify: `frontend-next/e2e/dashboard-interactions.spec.ts` only if the state assertions need explicit coverage.

**Interfaces:**
- Consumes: The compact summary and responsive table from Tasks 2–3.
- Produces: Regression coverage for `FAILED`, `BLOCKED`, and `WAITING_REVIEW`, plus verified frontend artifacts.

- [ ] **Step 1: Add explicit state assertions**

Use the existing mocked failed/blocked recovery rows and waiting-review polling test to assert:

```ts
await expect(row).toContainText("Recovery: Failed");
await expect(blockedRow).toContainText("Recovery: Blocked");
await expect(waitingReviewRow).toContainText("Recovery: Waiting review");
```

For each state, assert the `Run Now` button remains visible and that `View recovery` opens the detailed drawer when recovery data exists.

- [ ] **Step 2: Run static checks**

Run:

```bash
npm run typecheck
npm run lint
```

Expected: typecheck passes; lint has no errors. Existing font warnings may remain.

- [ ] **Step 3: Run production build using the repository rule**

Run:

```bash
npm run build
```

Expected: the script invokes `next build --webpack` and completes successfully.

- [ ] **Step 4: Run the complete E2E suite**

Run:

```bash
PLAYWRIGHT_PORT=3101 npm run test:e2e
```

Expected: all frontend interaction tests pass.

- [ ] **Step 5: Check diff hygiene and refresh CodeGraph**

Run:

```bash
git diff --check
codegraph sync
codegraph status
```

Expected: no whitespace errors and CodeGraph reports the index up to date.

