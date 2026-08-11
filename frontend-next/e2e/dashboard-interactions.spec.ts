import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // Keep browser tests deterministic and independent from the backend service.
  await page.route("**/api/**", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "API is not part of the FE interaction smoke test" }),
    });
  });
});

test("operator can navigate across the dashboard routes", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/review-center$/);
  await expect(page.getByRole("heading", { name: "Review Center", exact: true })).toBeVisible();

  const routes = [
    { label: "Reconciliation", path: "/reconciliation", title: "Reconciliation" },
    { label: "Schedules", path: "/schedules", title: "Schedules" },
    { label: "Audit Log", path: "/audit-log", title: "Audit Log" },
    { label: "Review Center", path: "/review-center", title: "Review Center" },
  ];

  for (const route of routes) {
    await page.getByRole("link", { name: route.label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${route.path}$`));
    await expect(page.getByRole("heading", { name: route.title, exact: true })).toBeVisible();
  }
});

test("operator can open Mapping Studio and switch mapping views", async ({ page }) => {
  await page.goto("/mapping-studio");

  await expect(page.getByRole("heading", { name: "Mapping Studio", exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Open Mapping Studio", exact: true }).click();
  await expect(page.getByRole("button", { name: "Paste Schema JSON", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Paste Schema JSON", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review Draft Mapping", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Schema JSON", exact: true }).click();
  await expect(page.locator('textarea[placeholder="Schema JSON..."]')).toBeVisible();
});

test("operator can recover a failed ViettelPay page from the schedules view", async ({ page }) => {
  let retryQueued = false;
  let postRetryListCalls = 0;
  let blockedResolved = false;

  const failedRecovery = {
    status: "FAILED",
    streamKey: "VIETTELPAY:API:scheduled:partner-settlement-window-2026-08-06-eu-west-1",
    mode: "SCHEDULED",
    lastCompletedUnitKey: "page:1:cursor-previous-settlement-window-2026-08-06",
    currentUnitKey: "page:2:cursor-previous-settlement-window-2026-08-06",
    currentPage: 2,
    cursorBefore: "cursor-1",
    attemptCount: 2,
    maxAttempts: 3,
    retryable: true,
    nextRetryAt: new Date(Date.now() + 45_000).toISOString(),
    errorCode: "fetch_timeout_partner_settlement_window_page_2",
    lastError: "Gateway timeout while fetching page 2 after the partner settlement window exceeded the upstream response budget.",
    completedUnitCount: 1,
    fetchedUnitCount: 1,
    totalUnitCount: 3,
    duplicateCount: 0,
    events: [
      { eventId: "page:1:PROCESSING", unitKey: "page:1", status: "PROCESSING", timestamp: "2026-08-06T04:00:00Z" },
      { eventId: "page:1:COMPLETED", unitKey: "page:1", status: "COMPLETED", timestamp: "2026-08-06T04:01:00Z" },
      { eventId: "page:2:FAILED", unitKey: "page:2", status: "FAILED", timestamp: "2026-08-06T04:02:00Z", errorCode: "fetch_timeout" },
    ],
    units: [
      { unitKey: "page:1", label: "Page 1", page: 1, status: "COMPLETED", attemptCount: 1 },
      { unitKey: "page:2", label: "Page 2", page: 2, status: "FAILED", attemptCount: 2, errorCode: "fetch_timeout" },
      { unitKey: "page:3", label: "Page 3", page: 3, status: "PENDING", attemptCount: 0 },
    ],
  };
  const processingRecovery = {
    ...failedRecovery,
    status: "PROCESSING",
    currentUnitKey: "page:2",
    retryable: null,
    nextRetryAt: null,
    units: [
      { ...failedRecovery.units[0] },
      { ...failedRecovery.units[1], status: "PROCESSING", errorCode: null },
      { ...failedRecovery.units[2] },
    ],
  };
  const completedRecovery = {
    ...failedRecovery,
    status: "COMPLETED",
    lastCompletedUnitKey: "page:3",
    currentUnitKey: null,
    currentPage: 3,
    cursorBefore: "cursor-2",
    retryable: false,
    nextRetryAt: null,
    errorCode: null,
    lastError: null,
    completedUnitCount: 3,
    fetchedUnitCount: 3,
    duplicateCount: 0,
    units: failedRecovery.units.map((unit) => ({ ...unit, status: "COMPLETED", errorCode: null })),
    events: failedRecovery.events.map((event) => event.status === "FAILED"
      ? { ...event, status: "COMPLETED", errorCode: null }
      : event),
  };
  const blockedRecovery = {
    ...failedRecovery,
    status: "BLOCKED",
    currentUnitKey: "page:2",
    retryable: false,
    nextRetryAt: null,
    errorCode: "pagination_parse_error",
    lastError: "Schema could not be parsed after maximum attempts.",
  };

  await page.route("**/api/v1/automation/jobs", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const recovery = !retryQueued
      ? failedRecovery
      : postRetryListCalls++ === 0
        ? processingRecovery
        : completedRecovery;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [{
          partner: "VIETTELPAY",
          fetchMethod: "API",
          schedule: "0 7 * * *",
          destination: "VIETTELPAY_SETTLEMENT",
          enabled: true,
          status: "HEALTHY",
          statusMessage: "Recovery state is available.",
          pendingReviewPackets: 0,
          recovery,
        }, {
          partner: "MOMO",
          fetchMethod: "API",
          schedule: "0 8 * * *",
          destination: "MOMO_SETTLEMENT",
          enabled: true,
          status: "HEALTHY",
          statusMessage: "Blocked recovery requires operator action.",
          pendingReviewPackets: 0,
          recovery: blockedResolved ? { ...blockedRecovery, status: "PENDING" } : blockedRecovery,
        }],
      }),
    });
  });

  await page.route("**/api/v1/automation/jobs/VIETTELPAY/recovery/retry", async (route) => {
    retryQueued = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        queued: true,
        actor: "playwright-operator",
        partner: "VIETTELPAY",
        message: "Recovery retry queued from checkpoint.",
        runtimeRunId: "run-viettelpay-recovery",
        resumedFromUnitKey: "page:2",
      }),
    });
  });

  await page.route("**/api/v1/automation/jobs/MOMO/recovery/resolve", async (route) => {
    blockedResolved = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        actor: "playwright-operator",
        partner: "MOMO",
        action: "SKIP",
        unitKey: "page:2",
        status: "DISCOVERED",
        message: "Recovery checkpoint resolved with action SKIP.",
      }),
    });
  });

  await page.goto("/schedules");
  const row = page.getByRole("row", { name: /VIETTELPAY/ });
  await expect(row).toContainText("Recovery: FAILED");
  const actions = row.locator("td").last();
  await expect(actions.getByRole("button", { name: "View recovery", exact: true })).toBeVisible();
  await expect(actions.getByRole("button", { name: "Run Now", exact: true })).toBeVisible();
  await expect(actions.getByRole("button", { name: "Run Now", exact: true })).toHaveCSS("white-space", "nowrap");
  await expect(row).toContainText("Progress");
  await expect(row).not.toContainText("Checkpoint");
  await expect(row).not.toContainText("Attempt");
  const recoveryFilter = page.getByLabel("Recovery status");
  await recoveryFilter.selectOption("FAILED");
  await expect(page).toHaveURL(/recovery=FAILED/);
  await expect(row).toBeVisible();
  await recoveryFilter.selectOption("COMPLETED");
  await expect(page.getByText("No partner matches this recovery status.")).toBeVisible();
  await recoveryFilter.selectOption("BLOCKED");
  const blockedRow = page.getByRole("row", { name: /MOMO/ });
  await expect(blockedRow).toContainText("Recovery: BLOCKED");
  await expect(blockedRow.getByRole("button", { name: "Run Now", exact: true })).toBeVisible();
  await blockedRow.getByRole("button", { name: "View recovery", exact: true }).click();
  const blockedDialog = page.getByRole("dialog");
  await blockedDialog.locator("#recovery-resolution-reason").fill("Validated terminal schema issue; skip this unit.");
  await blockedDialog.getByRole("button", { name: "Skip unit", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "resolved with action SKIP" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(blockedDialog).toBeHidden();
  await recoveryFilter.selectOption("ALL");
  await row.getByRole("button", { name: "View recovery", exact: true }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("page:1");
  await expect(dialog).toContainText("fetch_timeout");
  await expect(dialog).toContainText("Event timeline");
  await dialog.getByRole("button", { name: "Retry now", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Recovery retry queued" })).toBeVisible();

  await expect(row).toContainText("Recovery: COMPLETED", { timeout: 8_000 });
  await expect(dialog).toContainText("page:3", { timeout: 8_000 });
  await expect(dialog.locator("dt", { hasText: "Fetched units" }).locator("..").locator("dd")).toHaveText("3 of 3");

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("operator polling stops when a run enters waiting review", async ({ page }) => {
  let runQueued = false;
  let runListCalls = 0;

  await page.route("**/api/v1/automation/jobs", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    runListCalls += 1;
    const waitingReview = runQueued && runListCalls >= 3;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [{
          partner: "VIETTELPAY",
          fetchMethod: "API",
          schedule: "0 7 * * *",
          destination: "VIETTELPAY_SETTLEMENT",
          enabled: true,
          status: "HEALTHY",
          statusMessage: "Waiting for configuration approval.",
          pendingReviewPackets: 0,
          latestRuntimeRun: runQueued
            ? { id: "run-waiting-review", status: waitingReview ? "WAITING_REVIEW" : "PROCESSING" }
            : null,
          recovery: waitingReview ? {
            status: "WAITING_REVIEW",
            streamKey: "VIETTELPAY:API:scheduled",
            mode: "SCHEDULED",
            attemptCount: 1,
            maxAttempts: 3,
            retryable: false,
            completedUnitCount: 1,
            totalUnitCount: 2,
            duplicateCount: 0,
            units: [],
            events: [],
          } : null,
        }],
      }),
    });
  });

  await page.route("**/api/v1/automation/jobs/VIETTELPAY/run", async (route) => {
    runQueued = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, runtimeRunId: "run-waiting-review", message: "Run queued." }),
    });
  });

  await page.goto("/schedules");
  const row = page.getByRole("row", { name: /VIETTELPAY/ });
  const runButton = row.getByRole("button", { name: "Run Now", exact: true });
  await runButton.click();
  await expect(runButton).toHaveText("Run Now", { timeout: 5_000 });
  await expect(row).toContainText("Recovery: Waiting review");
  const callsAfterTerminal = runListCalls;
  await page.waitForTimeout(1_500);
  expect(runListCalls).toBe(callsAfterTerminal);
});
