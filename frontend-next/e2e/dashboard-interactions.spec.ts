import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // The icon font is decorative; block the external request so offline/CI
  // runs do not wait for a third-party font before the document is ready.
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  await page.route("https://fonts.gstatic.com/**", (route) => route.abort());

  // Mapping Studio loads its list before rendering the wizard. Keep that
  // unrelated endpoint deterministic; schedule tests provide their own
  // automation fixtures below.
  await page.route("**/api/v1/mappings**", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Mapping API is not part of this smoke test" }),
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
    // The sidebar icon is part of the accessible name, so match the visible
    // navigation label without requiring the icon text to be absent.
    await page.getByRole("link", { name: route.label }).click();
    await expect(page).toHaveURL(new RegExp(`${route.path}$`));
    await expect(page.getByRole("heading", { name: route.title, exact: true })).toBeVisible();
  }
});

test("review progress counts only unique reviewable reconciliation rows", async ({ page }) => {
  const results = [
    { id: "mismatch-1", partnerTxnId: "mismatch-1", reconciliationStatus: "MISSING_PARTNER" },
    { id: "mismatch-2", partnerTxnId: "mismatch-2", reconciliationStatus: "MISSING_PARTNER" },
  ];
  const reviewRecords = [
    { _id: "mismatch-1", recordKey: "mismatch-1", reviewed: true, notes: [], partner: "DEMO", date: "2026-08-28" },
    { _id: "mismatch-2", recordKey: "mismatch-2", reviewed: true, notes: [], partner: "DEMO", date: "2026-08-28" },
    { _id: "matched-1", recordKey: "matched-1", reviewed: true, notes: [], partner: "DEMO", date: "2026-08-28" },
  ];

  await page.route("**/api/v1/reconciliation/**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return route.fallback();
    if (url.pathname.endsWith("/stats")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ partner: "DEMO", date: "2026-08-28", total: 20, byStatus: { MATCHED: 18, MISSING_PARTNER: 2 }, totalPartnerAmount: null, totalInternalAmount: null }),
      });
      return;
    }
    if (url.pathname.endsWith("/results")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ results, total: results.length, limit: 100, offset: 0 }) });
      return;
    }
    if (url.pathname.endsWith("/review-records")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ records: reviewRecords }) });
      return;
    }
    if (url.pathname.endsWith("/run-status")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run: null }) });
      return;
    }
    if (url.pathname.endsWith("/insights")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    await route.fallback();
  });

  await page.goto("/reconciliation");
  await expect(page.getByText("2/2 (100%)", { exact: true })).toBeVisible();
  await expect(page.getByText("3/2 (150%)", { exact: true })).toHaveCount(0);
});

test("does not label a terminal partial reconciliation as pending review", async ({ page }) => {
  await page.route("**/api/v1/reconciliation/**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return route.fallback();
    if (url.pathname.endsWith("/run-status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          run: {
            status: "PARTIAL",
            message: "Reconciliation completed after quarantine review.",
            stats: { outcome: "PARTIAL", resultCount: 20 },
          },
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/stats")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          partner: "DEMO",
          date: "2026-08-28",
          total: 20,
          byStatus: { MATCHED: 18, MISSING_PARTNER: 2 },
          totalPartnerAmount: null,
          totalInternalAmount: null,
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/results")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results: [], total: 0, limit: 100, offset: 0 }),
      });
      return;
    }
    if (url.pathname.endsWith("/review-records")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ records: [] }) });
      return;
    }
    if (url.pathname.endsWith("/insights")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    await route.fallback();
  });

  await page.goto("/reconciliation");
  await expect(page.getByText("● PARTIAL", { exact: true })).toBeVisible();
  const throughput = page.getByText("Ingestion Throughput", { exact: true }).locator("..");
  await expect(throughput.getByText("Completed with rejects", { exact: true })).toBeVisible();
  await expect(throughput.getByText("Pending Review", { exact: true })).toHaveCount(0);
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

test("operator can keep the validation trace preview compact until requested", async ({ page }) => {
  const packet = {
    _id: "packet-preview-1",
    partner: "VNPAY",
    fileName: "settlement_VNPAY_20260810.xlsx",
    fileTypeDetected: "SETTLEMENT",
    status: "PENDING",
    createdAt: "2026-08-10T00:00:00Z",
    sourceType: "SCHEDULER_JOB",
    reconciliationDate: "2026-08-10T00:00:00Z",
    recommendedAction: { actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME", reason: "Draft mapping requires review." },
    riskSummary: { severity: "low" },
    parseStrategy: { sheetName: "Sheet1", startRow: 2, fieldMappingCount: 1 },
    structureSignature: { headers: ["id"], firstDataRowIndex: 2 },
    validationGates: [{
      gateKey: "runtime_validation",
      status: "pass",
      label: "Runtime validation",
      details: {
        sampledRows: 1,
        successRows: 1,
        failedRows: 0,
        traceSamples: [{ row: 1, normalizedData: { id: "VNPAY-001" }, fieldTraces: [{ path: "id", sourceField: "id", sourceValue: "VNPAY-001", outputValue: "VNPAY-001", status: "ok" }] }],
      },
    }],
    samplePreview: [{ id: "row-1", values: { id: "VNPAY-001" } }],
    internalRecordCount: 1,
    internalPreview: [{ id: "internal-1", partnerTxnId: "TRACE-001", amount: "100", currency: "VND", status: "SUCCESS", transactionTime: "2026-08-10T12:00:00+07:00" }],
  };

  await page.route("**/api/v1/review-packets**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ packets: [packet] }) });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/v1/review-packets/packet-preview-1", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ packet }) });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/v1/review-packets/packet-preview-1/classify-scope-llm", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        suggestedScope: "FULL_SNAPSHOT",
        probabilities: { FULL_SNAPSHOT: 1, INCREMENTAL_APPEND: 0, REPLACEMENT: 0 },
        reasoning: "Deterministic fixture scope.",
        internalDbRecordCount: 1,
        internalPreview: packet.internalPreview,
        receivedRecordCount: 1,
      }),
    });
  });
  await page.route("**/api/v1/review-packets/packet-preview-1/scope", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.route("**/api/v1/review-packets/packet-preview-1/generate-ai-mapping", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ mapping: { fieldMappings: [{ path: "id", column: 1, type: "STRING", required: true }], configHealth: { reasoning: "Fixture mapping." } } }),
    });
  });

  await page.goto("/review-center");
  await page.getByRole("button", { name: "Open Review", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Continue", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Partner Mapping Validation", exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Show runtime trace samples", exact: true })).toBeVisible();
  await expect(dialog.getByText("Sample Row 1", { exact: true })).toBeHidden();

  await dialog.getByRole("button", { name: "Show runtime trace samples", exact: true }).click();
  await expect(dialog.getByText("Sample Row 1", { exact: true })).toBeVisible();
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

  await page.route("**/api/v1/automation/jobs**", async (route) => {
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

  await page.route("**/api/v1/automation/jobs/VIETTELPAY/recovery/retry**", async (route) => {
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

  await page.route("**/api/v1/automation/jobs/MOMO/recovery/resolve**", async (route) => {
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
  await expect(row).toContainText("Failed");
  const actions = row.locator("td").last();
  await expect(actions.getByRole("button", { name: /Retry/ })).toBeVisible();
  await expect(actions.getByRole("button", { name: /Retry/ })).toHaveCSS("white-space", "nowrap");
  await expect(row).toContainText("fetch_timeout_partner_settlement_window_page_2");
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
  await expect(blockedRow).toContainText("Blocked");
  await expect(blockedRow.getByRole("button", { name: /Retry/ })).toBeVisible();
  await blockedRow.getByRole("button", { name: /More options for MOMO/ }).click();
  await blockedRow.getByRole("menuitem", { name: /View runtime details/ }).click();
  const blockedDialog = page.getByRole("dialog");
  await blockedDialog.locator("#recovery-resolution-reason").fill("Validated terminal schema issue; skip this unit.");
  await blockedDialog.getByRole("button", { name: "Skip unit", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "resolved with action SKIP" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(blockedDialog).toBeHidden();
  await recoveryFilter.selectOption("ALL");
  await actions.getByRole("button", { name: /More options for VIETTELPAY/ }).click();
  await actions.getByRole("menuitem", { name: /View runtime details/ }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("page:1");
  await expect(dialog).toContainText("fetch_timeout");
  await expect(dialog).toContainText("Event timeline");
  await dialog.getByRole("button", { name: "Retry now", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Recovery retry queued" })).toBeVisible();

  await expect(row).toContainText("Ready", { timeout: 8_000 });
  await expect(dialog).toContainText("page:3", { timeout: 8_000 });
  await expect(dialog.locator("dt", { hasText: "Fetched units" }).locator("..").locator("dd")).toHaveText("3 of 3");

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("operator polling stops when a run enters waiting review", async ({ page }) => {
  let runQueued = false;
  let runListCalls = 0;

  await page.route("**/api/v1/automation/jobs**", async (route) => {
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
              units: [{ unitKey: "page:2", label: "Page 2", page: 2, status: "WAITING_REVIEW", attemptCount: 1 }],
              events: [{ eventId: "page:2:WAITING_REVIEW", unitKey: "page:2", status: "WAITING_REVIEW", timestamp: "2026-08-10T04:00:00Z" }],
            } : null,
        }],
      }),
    });
  });

  await page.route("**/api/v1/automation/jobs/VIETTELPAY/run**", async (route) => {
    runQueued = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, runtimeRunId: "run-waiting-review", message: "Run queued." }),
    });
  });

  await page.goto("/schedules");
  const row = page.getByRole("row", { name: /VIETTELPAY/ });
  const runButton = row.getByRole("button", { name: /Run/ });
  await runButton.click();
  await expect(runButton).toContainText("Run", { timeout: 5_000 });
  await expect(row).toContainText("Waiting Review");
  await row.getByRole("button", { name: /More options for VIETTELPAY/ }).click();
  await row.getByRole("menuitem", { name: /View runtime details/ }).click();
  const waitingDialog = page.getByRole("dialog");
  await expect(waitingDialog.locator('[class*="markerWAITING_REVIEW"]')).toHaveCSS("color", "rgb(240, 185, 11)");
  await page.keyboard.press("Escape");
  const callsAfterTerminal = runListCalls;
  await page.waitForTimeout(1_500);
  expect(runListCalls).toBe(callsAfterTerminal);
});

test("operator keeps the newest schedule state when polling responses finish out of order", async ({ page }) => {
  let runListCalls = 0;
  await page.route("**/api/v1/automation/jobs**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    runListCalls += 1;
    const requestNumber = runListCalls;
    if (requestNumber === 2) await new Promise((resolve) => setTimeout(resolve, 3_500));
    const waitingReview = requestNumber >= 3;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [{
          partner: "VNPAY",
          fetchMethod: "FILEDROP",
          schedule: "0 7 * * *",
          destination: "VNPAY_SETTLEMENT",
          enabled: true,
          status: waitingReview ? "WAITING_REVIEW" : "FETCHING",
          statusMessage: waitingReview ? "Mapping approval is required." : "Fetching source units.",
          pendingReviewPackets: waitingReview ? 1 : 0,
          latestRuntimeRun: { id: "run-vnpay", status: waitingReview ? "WAITING_REVIEW" : "FETCHING" },
          recovery: waitingReview ? { status: "WAITING_REVIEW", units: [], events: [] } : null,
        }],
      }),
    });
  });

  await page.goto("/schedules");
  const row = page.getByRole("row", { name: /VNPAY/ });
  await expect(row).toContainText("Waiting Review");
  const callsAfterTerminal = runListCalls;
  await page.waitForTimeout(1_500);
  expect(runListCalls).toBe(callsAfterTerminal);
});

test("operator can start a VNPAY backfill and see its approval progress", async ({ page }) => {
  await page.route("**/api/v1/automation/jobs**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [{
          partner: "VNPAY",
          fetchMethod: "FILEDROP",
          schedule: "none",
          destination: "VNPAY_SETTLEMENT",
          enabled: true,
          status: "HEALTHY",
          pendingReviewPackets: 1,
          latestRuntimeRun: null,
          activeBackfill: {
            _id: "backfill-vnpay-1",
            partner: "VNPAY",
            fetchConfigId: "vnpay-fetch-config",
            mode: "BACKFILL",
            status: "WAITING_CONFIG",
            fromDate: "2026-08-07",
            toDate: "2026-08-11",
            currentDate: "2026-08-10",
            completedDays: 1,
            totalDays: 3,
            approvalRequired: true,
            days: [],
          },
          recentPackets: [{ _id: "packet-vnpay-1", partner: "VNPAY", fileName: "settlement_VNPAY.xlsx", status: "PENDING", sourceType: "SCHEDULER_JOB", createdAt: "2026-08-07T00:00:00Z" }],
          recovery: null,
        }],
      }),
    });
  });

  await page.route("**/api/v1/automation/jobs/VNPAY/backfill**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        _id: "backfill-vnpay-1",
        partner: "VNPAY",
        fetchConfigId: "vnpay-fetch-config",
        mode: "BACKFILL",
        status: "WAITING_CONFIG",
        fromDate: "2026-08-07",
        toDate: "2026-08-11",
        currentDate: "2026-08-07",
        completedDays: 0,
        totalDays: 3,
        approvalRequired: true,
        approvalContext: { reviewPacketId: "packet-vnpay-1" },
        days: [
          { businessDate: "2026-08-07", status: "PENDING" },
          { businessDate: "2026-08-10", status: "PENDING" },
          { businessDate: "2026-08-11", status: "PENDING" },
        ],
      }),
    });
  });

  await page.route("**/api/v1/automation/backfill-runs/backfill-vnpay-1**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        _id: "backfill-vnpay-1",
        partner: "VNPAY",
        status: "WAITING_CONFIG",
        fromDate: "2026-08-07",
        toDate: "2026-08-11",
        completedDays: 0,
        totalDays: 3,
        approvalRequired: true,
        approvalContext: { reviewPacketId: "packet-vnpay-1" },
        days: [
          { businessDate: "2026-08-07", status: "PENDING" },
          { businessDate: "2026-08-10", status: "PENDING" },
          { businessDate: "2026-08-11", status: "PENDING" },
        ],
      }),
    });
  });

  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto("/schedules");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const row = page.getByRole("row", { name: /VNPAY/ });
  await expect(row).toContainText("Backfill Review");
  await row.getByRole("button", { name: /More options for VNPAY/ }).click();
  await expect(row.getByRole("menuitem", { name: /Open pending review/ })).toBeVisible();
  await row.getByRole("menuitem", { name: /Open pending review/ }).click();
  await expect(page).toHaveURL(/\/review-center\?packet=packet-vnpay-1/);
  await page.goto("/schedules");
  await expect(page.getByRole("row", { name: /VNPAY/ })).toBeVisible();
  const refreshedRow = page.getByRole("row", { name: /VNPAY/ });
  const blockedRunButton = refreshedRow.getByRole("button", { name: "Run", exact: true });
  await expect(blockedRunButton).toHaveAttribute("aria-disabled", "true");
  // The action stays clickable so the operator receives the backfill guidance toast.
  // Playwright treats aria-disabled as non-actionable, so force the synthetic click
  // while preserving the accessibility state asserted above.
  await blockedRunButton.click({ force: true });
  await expect(page.getByRole("alert").filter({ hasText: "Backfill is WAITING CONFIG at 2026-08-10" })).toBeVisible();
  await refreshedRow.getByRole("button", { name: /More options for VNPAY/ }).click();
  await expect(refreshedRow.getByRole("menuitem", { name: "Run schedule now", exact: true })).toHaveAttribute("aria-disabled", "true");
  await expect(refreshedRow.getByRole("menuitem", { name: /Backfill date range/ })).toBeVisible();
  await refreshedRow.getByRole("menuitem", { name: /Backfill date range/ }).click();

  const formDialog = page.getByRole("dialog");
  await expect(formDialog).toContainText("Backfill VNPAY");
  await expect(formDialog.getByLabel("From date")).toHaveValue("2026-08-10");
  await expect(formDialog.getByLabel("To date")).toHaveValue("2026-08-11");
  await formDialog.getByLabel("From date").fill("2026-08-12");
  await formDialog.getByLabel("To date").fill("2026-08-11");
  await expect(formDialog.getByRole("alert")).toContainText("on or before");
  await formDialog.getByLabel("From date").fill("2026-08-07");
  await formDialog.getByRole("button", { name: "Start Backfill", exact: true }).click();

  const progressDialog = page.getByRole("dialog");
  await expect(progressDialog).toContainText("0/3 days");
  await expect(progressDialog).toContainText("Mapping approval required");
  await expect(progressDialog.getByRole("button", { name: "Open Guided Review", exact: true })).toBeVisible();
});

test("operator can inspect persisted ingestion observability from runtime details", async ({ page }) => {
  await page.route("**/api/v1/automation/jobs**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [{
          partner: "MOMO",
          fetchMethod: "FILEDROP",
          schedule: "0 7 * * *",
          destination: "MOMO_SETTLEMENT",
          enabled: true,
          status: "PARTIAL",
          latestRuntimeRun: {
            id: "runtime-observability-1",
            status: "PARTIAL",
            sourceFileId: "file-observability-1",
            updatedAt: "2026-09-03T07:00:03Z",
            stageSummary: {
              currentStage: "PERSISTING",
              stageDurationsMs: { READING: 12.5, PROCESSING: 34.25, PERSISTING: 8.75 },
              inputRows: 100,
              persistedRows: 92,
              rejectedRows: 5,
              duplicateRows: 2,
              persistenceFailedRows: 1,
              quarantinedRows: 5,
              currentUnitKey: "settlement-2026-09-03",
              currentPage: 2,
              durationMs: 987.6,
              batchMetrics: {
                parseRowsMs: 4.5,
                normalizeMs: 8.25,
                validateMs: 6.75,
                copyMs: 11.5,
                insertClassifyMs: 18.25,
                transactionOverheadMs: 2.5,
                totalBatchWallMs: 32.25,
                persistenceWindowMs: 28.5,
              },
              quality: { decision: "REVIEW", topRuleCodes: ["INVALID_AMOUNT", "DUPLICATE_KEY"] },
              lastErrorCode: "source_persist_error",
              lastError: "One batch could not be persisted.",
            },
          },
          recovery: null,
        }],
      }),
    });
  });

  await page.goto("/schedules");
  const row = page.getByRole("row", { name: /MOMO/ });
  await row.getByRole("button", { name: /More options for MOMO/ }).click();
  await row.getByRole("menuitem", { name: /View runtime details/ }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Ingestion observability", exact: true })).toBeVisible();
  await expect(dialog).toContainText("COMPLETED WITH REJECTS");
  await expect(dialog).toContainText("PERSISTING");
  await expect(dialog).toContainText("987.60 ms");
  await expect(dialog).toContainText("Input rows");
  await expect(dialog).toContainText("100");
  await expect(dialog).toContainText("Parse rows");
  await expect(dialog).toContainText("4.50 ms");
  await expect(dialog).toContainText("COPY");
  await expect(dialog).toContainText("REVIEW");
  await expect(dialog).toContainText("INVALID_AMOUNT, DUPLICATE_KEY");
  await expect(dialog).toContainText("Last persisted snapshot");
});

test("legacy runtime details show no persisted snapshot instead of zero counters", async ({ page }) => {
  await page.route("**/api/v1/automation/jobs**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [{
          partner: "VNPAY",
          fetchMethod: "API",
          schedule: "0 7 * * *",
          destination: "VNPAY_SETTLEMENT",
          enabled: true,
          status: "HEALTHY",
          latestRuntimeRun: {
            id: "legacy-runtime-1",
            status: "COMPLETED",
            updatedAt: "2026-09-03T07:00:03Z",
          },
          recovery: null,
        }],
      }),
    });
  });

  await page.goto("/schedules");
  const row = page.getByRole("row", { name: /VNPAY/ });
  await row.getByRole("button", { name: /More options for VNPAY/ }).click();
  await row.getByRole("menuitem", { name: /View runtime details/ }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("No persisted snapshot yet.");
  await expect(dialog.getByText("Input rows", { exact: true })).toHaveCount(0);
});
