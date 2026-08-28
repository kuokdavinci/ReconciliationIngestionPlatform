import { expect, test, type Page } from "@playwright/test";

const records = [
  { id: "record-invalid", scenario: "DEMO-INVALID-001", status: "PENDING", priority: "NORMAL", errorCode: "MISSING_REQUIRED_FIELD", sourceUnitKey: "demo-unit-invalid-001" },
  { id: "record-duplicate", scenario: "DEMO-DUPLICATE-001", status: "PENDING", priority: "HIGH", errorCode: "CONFLICTING_DUPLICATE", sourceUnitKey: "demo-unit-duplicate-001" },
  { id: "record-reprocess", scenario: "DEMO-REPROCESS-001", status: "REPROCESSING", priority: "NORMAL", errorCode: "INVALID_TIMESTAMP", sourceUnitKey: "demo-unit-reprocess-001", claimedBy: "demo-operator" },
  { id: "record-accept", scenario: "DEMO-ACCEPT-001", status: "REPROCESSING", priority: "NORMAL", errorCode: "EQUIVALENT_DUPLICATE", sourceUnitKey: "demo-unit-accept-001", claimedBy: "demo-operator" },
  { id: "record-reject", scenario: "DEMO-REJECT-001", status: "REJECTED", priority: "NORMAL", errorCode: "MALFORMED_ROW", sourceUnitKey: "demo-unit-reject-001" },
  { id: "record-escalated", scenario: "DEMO-ESCALATED-001", status: "PENDING", priority: "NORMAL", errorCode: "MISSING_REQUIRED_FIELD", sourceUnitKey: "demo-unit-escalated-001", escalationLevel: 2, overdue: true },
  { id: "record-recovery", scenario: "DEMO-RECOVERY-001", status: "PENDING", priority: "NORMAL", errorCode: "SOURCE_UNIT_RECOVERY_REQUIRED", sourceUnitKey: "demo-unit-recovery-001" },
];

const issueTypes: Record<string, string> = {
  MISSING_REQUIRED_FIELD: "REQUIRED_FIELD",
  CONFLICTING_DUPLICATE: "DUPLICATE",
  EQUIVALENT_DUPLICATE: "DUPLICATE",
  INVALID_TIMESTAMP: "FORMAT",
  SOURCE_UNIT_RECOVERY_REQUIRED: "RECOVERY",
  MALFORMED_ROW: "FORMAT",
};

function reviewButton(page: Page, scenario: string) {
  return page.getByTestId(`quarantine-row-${scenario}`).getByRole("button", { name: "Review now" });
}

function listItem(record: (typeof records)[number]) {
  return {
    _id: record.id,
    sourceFileId: `${record.scenario}-file`,
    sourceUnitKey: record.sourceUnitKey,
    partner: "DEMO",
    reconciliationDate: "2026-08-27T03:00:00Z",
    rowNumber: 1,
    phase: "VALIDATION",
    severity: "RECORD",
    configVersion: "DEMO_v01",
    status: record.status,
    attemptCount: record.status === "REPROCESSING" ? 2 : 1,
    claimedBy: record.claimedBy ?? null,
    claimExpiresAt: record.claimedBy ? "2026-08-27T04:00:00Z" : null,
    priority: record.priority,
    reviewDueAt: record.overdue ? "2026-08-26T03:00:00Z" : "2026-08-28T03:00:00Z",
    escalationLevel: record.escalationLevel ?? 0,
    errorCodes: [record.errorCode],
    issueType: issueTypes[record.errorCode] ?? "OTHER",
    issueSummary: record.errorCode === "MALFORMED_ROW" ? "Missing amount" : `${issueTypes[record.errorCode] ?? "Other"} issue`,
    lastActionActor: record.status === "REJECTED" ? "demo-operator" : null,
    lastActionAt: record.status === "REJECTED" ? "2026-08-28T03:00:00Z" : null,
    resolutionMetadata: { demoScenarioId: record.scenario, demoTitle: `${record.scenario} demo case` },
    createdAt: "2026-08-27T03:00:00Z",
    updatedAt: "2026-08-27T03:00:00Z",
  };
}

function detailItem(record: (typeof records)[number]) {
  const isRequiredField = record.errorCode === "MISSING_REQUIRED_FIELD";
  const isDuplicate = record.errorCode === "CONFLICTING_DUPLICATE" || record.errorCode === "EQUIVALENT_DUPLICATE";
  const isMissingAmount = record.errorCode === "MALFORMED_ROW";
  return {
    ...listItem(record),
    rawRow: {
      id: `${record.scenario}-TX`,
      ...(isMissingAmount ? {} : { amount: "125000" }),
      currency: "VND",
      status: "SUCCESS",
      transDate: "2026-08-27T03:00:00Z",
      secret: "DO-NOT-RENDER",
    },
    errors: [{ errorCode: record.errorCode, reason: "Bounded demo evidence", rawRow: { secret: "DO-NOT-RENDER" } }],
    evidence: {
      sampleFields: [
        { sourceField: "id", canonicalPath: "id", column: null, value: `${record.scenario}-TX`, state: "OK" },
        { sourceField: "amount", canonicalPath: "amount", column: null, value: isMissingAmount ? null : "125000", state: isMissingAmount ? "MISSING" : "OK" },
        { sourceField: "currency", canonicalPath: "currency", column: null, value: "VND", state: "OK" },
        { sourceField: "status", canonicalPath: "status", column: null, value: isRequiredField ? null : "SUCCESS", state: isRequiredField ? "MISSING" : "OK" },
        { sourceField: "transDate", canonicalPath: "transDate", column: null, value: "2026-08-27T03:00:00Z", state: "OK" },
      ],
      ...(isRequiredField ? {
        mapping: {
          configVersion: "DEMO_v01",
          requiredFields: [
            { canonicalPath: "id", sourceField: "id", column: null, type: "STRING", state: "PRESENT" },
            { canonicalPath: "amount", sourceField: "amount", column: null, type: "DECIMAL", state: "PRESENT" },
            { canonicalPath: "currency", sourceField: "currency", column: null, type: "STRING", state: "PRESENT" },
            { canonicalPath: "status", sourceField: "status", column: null, type: "MAPPING", state: "MISSING" },
          ],
          observedColumns: ["id", "amount", "currency"],
        },
      } : {}),
      ...(isDuplicate ? {
        duplicate: {
          status: record.errorCode === "EQUIVALENT_DUPLICATE" ? "EQUIVALENT" : "CONFLICT",
          fields: [
            { name: "id", incoming: `${record.scenario}-TX`, existing: `${record.scenario}-TX`, result: "MATCH" },
            { name: "trace", incoming: "TRACE-DEMO-DUPLICATE-001-TX", existing: "TRACE-DEMO-DUPLICATE-001-TX", result: "MATCH" },
            { name: "amount", incoming: "125000", existing: record.errorCode === "EQUIVALENT_DUPLICATE" ? "125000" : "99000", result: record.errorCode === "EQUIVALENT_DUPLICATE" ? "MATCH" : "DIFF" },
            { name: "currency", incoming: "VND", existing: "VND", result: "MATCH" },
            { name: "status", incoming: "SUCCESS", existing: "SUCCESS", result: "MATCH" },
          ],
        },
      } : {}),
    },
    resolutionHistory: [],
  };
}

test.beforeEach(async ({ page }) => {
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  await page.route("https://fonts.gstatic.com/**", (route) => route.abort());
  await page.route("**/api/v1/review-packets**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ packets: [] }) });
  });
});

test("operator can review and claim a bounded quarantine case", async ({ page }) => {
  const actions: Array<{ path: string; body: Record<string, unknown> }> = [];

  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET") {
      if (url.pathname.endsWith("/quarantine")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: records.map(listItem),
            nextCursor: null,
            limit: 100,
            summary: { pending: 4, reprocessing: 2, resolved: 0, rejected: 1, overdue: 2, highPriority: 1 },
          }),
        });
        return;
      }
      const record = records.find((item) => url.pathname.endsWith(`/${item.id}`));
      if (record) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailItem(record)) });
        return;
      }
    }

    const body = request.postDataJSON() as Record<string, unknown>;
    actions.push({ path: url.pathname, body });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        recordId: "record-invalid",
        actionId: body.actionId,
        outcome: "CLAIMED",
        previousStatus: "PENDING",
        status: "REPROCESSING",
        attemptCount: 2,
        claimedBy: "demo-operator",
        priority: "NORMAL",
        reviewDueAt: "2026-08-28T03:00:00Z",
        escalationLevel: 0,
        sourceEvidenceAvailable: null,
        qualityCounters: {},
        errorCodes: [],
      }),
    });
  });

  await page.goto("/review-center?tab=quarantine");
  await expect(page.getByRole("tab", { name: "Quarantine" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Review Packets" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quarantine review" })).toBeVisible();
  await expect(page.getByTestId("quarantine-row-DEMO-INVALID-001")).toBeVisible();
  await expect(page.getByTestId("quarantine-row-DEMO-DUPLICATE-001")).toBeVisible();
  await expect(page.getByText("Action by: demo-operator", { exact: true })).toBeVisible();
  await expect(page.getByText("Missing amount", { exact: true })).toBeVisible();
  await expect(page.getByLabel("2 overdue")).toBeVisible();
  await expect(page.getByLabel("Operator actor")).toHaveValue("demo-operator");

  await page.getByLabel("Operator actor").fill("demo-operator");
  await reviewButton(page, "DEMO-INVALID-001").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("MISSING_REQUIRED_FIELD");
  await expect(dialog.getByRole("heading", { name: "Validation issue" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Offending row" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Source context" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Review status" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Recommended action", exact: true })).toBeVisible();
  await expect(dialog.getByRole("table", { name: "Required field evidence" })).toContainText("125000");
  await expect(dialog.getByRole("table", { name: "Required field evidence" })).toContainText("VND");
  const detailPanel = dialog.getByTestId("quarantine-detail-panel");
  await expect(detailPanel).toHaveCount(1);
  await expect.poll(async () => detailPanel.evaluate((element) => getComputedStyle(element).fontFamily)).toContain("Plus Jakarta Sans");
  await expect(dialog).not.toContainText("DO-NOT-RENDER");
  await expect(dialog).not.toContainText("fingerprint");

  await dialog.getByRole("button", { name: "Claim", exact: true }).click();
  await dialog.getByRole("button", { name: "Confirm claim", exact: true }).click();
  await expect(page.getByText("CLAIMED", { exact: true })).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Recommended action", exact: true })).toBeVisible();
  expect(actions).toHaveLength(1);
  expect(actions[0].path).toBe("/api/v1/quarantine/record-invalid/claim");
  expect(actions[0].body).toMatchObject({ operatorId: "demo-operator", expectedStatus: "PENDING" });
  expect(actions[0].body.actionId).toEqual(expect.any(String));
});

test("quarantine detail exposes the action controls for the demo workflow", async ({ page }) => {
  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/quarantine")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: records.map(listItem), nextCursor: null, limit: 100, summary: { pending: 4, reprocessing: 2, resolved: 0, rejected: 1, overdue: 2, highPriority: 1 } }) });
      return;
    }
    if (request.method() === "GET") {
      const record = records.find((item) => url.pathname.endsWith(`/${item.id}`));
      if (record) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailItem(record)) });
        return;
      }
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ outcome: "OK" }) });
  });

  await page.goto("/review-center?tab=quarantine");
  await page.getByLabel("Operator actor").fill("demo-operator");
  await reviewButton(page, "DEMO-REPROCESS-001").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Reprocess" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Accept existing" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Reject" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Escalate" })).toBeVisible();
});

test("operator can submit reprocess, accept-existing, reject, escalate and resume actions", async ({ page }) => {
  const actions: Array<{ path: string; body: Record<string, unknown> }> = [];

  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/quarantine")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: records.map(listItem), nextCursor: null, limit: 100, summary: { pending: 4, reprocessing: 2, resolved: 0, rejected: 1, overdue: 2, highPriority: 1 } }) });
      return;
    }
    if (request.method() === "GET") {
      const record = records.find((item) => url.pathname.endsWith(`/${item.id}`));
      if (record) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailItem(record)) });
        return;
      }
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    actions.push({ path: url.pathname, body });
    const outcome = url.pathname.endsWith("/reprocess")
      ? "RESOLVED"
      : url.pathname.endsWith("/accept-existing")
        ? "ACCEPTED_EXISTING"
        : url.pathname.endsWith("/reject")
          ? "REJECTED"
          : url.pathname.endsWith("/escalate")
            ? "ESCALATED"
            : "RESUMED";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ outcome, status: outcome === "ESCALATED" ? "PENDING" : "RESOLVED", actionId: body.actionId }) });
  });

  await page.goto("/review-center?tab=quarantine");
  await page.getByLabel("Operator actor").fill("demo-operator");

  await reviewButton(page, "DEMO-REPROCESS-001").click();
  await page.getByRole("dialog").getByRole("button", { name: "Reprocess", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm reprocess", exact: true }).click();
  await expect(page.getByText("RESOLVED", { exact: true }).last()).toBeVisible();
  await page.getByRole("dialog").getByText("Close", { exact: true }).click();

  await reviewButton(page, "DEMO-ACCEPT-001").click();
  await page.getByRole("dialog").getByRole("button", { name: "Accept existing", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm accept existing", exact: true }).click();
  await page.getByRole("dialog").getByText("Close", { exact: true }).click();

  await reviewButton(page, "DEMO-REPROCESS-001").click();
  await page.getByRole("dialog").getByRole("button", { name: "Reject", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm reject", exact: true }).click();
  await expect(page.getByText("A non-empty reason is required for this action.", { exact: true })).toBeVisible();
  await page.getByLabel("Reason").fill("Confirmed outside the settlement scope.");
  await page.getByRole("dialog").getByRole("button", { name: "Confirm reject", exact: true }).click();
  await page.getByRole("dialog").getByText("Close", { exact: true }).click();

  await reviewButton(page, "DEMO-DUPLICATE-001").click();
  await page.getByRole("dialog").getByRole("button", { name: "Escalate", exact: true }).click();
  await page.getByLabel("Reason").fill("Partner operations need a second review.");
  await page.getByRole("dialog").getByRole("button", { name: "Confirm escalate", exact: true }).click();
  await page.getByRole("dialog").getByText("Close", { exact: true }).click();

  await reviewButton(page, "DEMO-RECOVERY-001").click();
  await page.getByRole("dialog").getByRole("button", { name: "Resume source unit", exact: true }).click();
  await page.getByLabel("Reason").fill("Source payload is available for recovery.");
  await page.getByRole("dialog").getByRole("button", { name: "Confirm resume source unit", exact: true }).click();

  expect(actions.map((item) => item.path)).toEqual([
    "/api/v1/quarantine/record-reprocess/reprocess",
    "/api/v1/quarantine/record-accept/accept-existing",
    "/api/v1/quarantine/record-reprocess/reject",
    "/api/v1/quarantine/record-duplicate/escalate",
    "/api/v1/quarantine/source-units/demo-unit-recovery-001/resume",
  ]);
  for (const action of actions) {
    expect(action.body.operatorId).toBe("demo-operator");
    expect(action.body.actionId).toEqual(expect.any(String));
  }
});

test("queue filters and cursor pagination are sent to the bounded API", async ({ page }) => {
  const requests: URL[] = [];
  let pageNumber = 0;
  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/quarantine")) {
      requests.push(url);
      const filtered = pageNumber > 0 ? [records[1]] : records;
      pageNumber += 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: filtered.map(listItem), nextCursor: url.searchParams.has("cursor") ? null : "cursor-1", limit: 100, summary: { pending: 4, reprocessing: 2, resolved: 0, rejected: 1, overdue: 2, highPriority: 1 } }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...detailItem(records[0]), resolutionHistory: [] }) });
  });

  await page.goto("/review-center?tab=quarantine");
  await page.getByLabel("Quarantine issue type").selectOption("DUPLICATE");
  await expect.poll(() => requests.some((url) => url.searchParams.get("issueType") === "DUPLICATE")).toBe(true);
  await page.getByLabel("Quarantine priority").selectOption("HIGH");
  await expect.poll(() => requests.some((url) => url.searchParams.get("priority") === "HIGH")).toBe(true);
  await expect(page.getByTestId("quarantine-row-DEMO-DUPLICATE-001")).toBeVisible();
  await page.getByRole("button", { name: "Next page" }).click();
  await expect.poll(() => requests.some((url) => url.searchParams.get("cursor") === "cursor-1")).toBe(true);
});

test("quarantine batch is presented as a parent packet with an explicit proceed action", async ({ page }) => {
  const continueCalls: string[] = [];
  const parentRecord = {
    ...listItem(records[4]),
    reviewPacketId: "packet-parent",
    postApprovalRunId: "run-parent",
  };

  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/quarantine")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [parentRecord],
          nextCursor: null,
          limit: 100,
          summary: { pending: 0, reprocessing: 0, resolved: 0, rejected: 1, overdue: 0, highPriority: 0 },
          groups: [{
            groupKey: "run-parent",
            reviewPacketId: "packet-parent",
            postApprovalRunId: "run-parent",
            sourceFileId: parentRecord.sourceFileId,
            partner: "DEMO",
            total: 1,
            pending: 0,
            reprocessing: 0,
            resolved: 0,
            rejected: 1,
            overdue: 0,
            highPriority: 0,
            issueTypes: ["FORMAT"],
          }],
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailItem(records[4])) });
  });
  await page.route("**/api/v1/review-packets/packet-parent/post-approve-run/continue", async (route) => {
    continueCalls.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, outcome: "RECONCILED_AFTER_QUARANTINE", reconciliationCount: 1 }),
    });
  });

  await page.goto("/review-center?tab=quarantine");
  await expect(page.getByText("Packet: packet-parent · Run: run-parent")).toBeVisible();
  const proceed = page.getByRole("button", { name: "Proceed to reconciliation" });
  await expect(proceed).toBeVisible();
  await proceed.click();
  await expect.poll(() => continueCalls).toHaveLength(1);
  await expect(page.getByText("Reconciliation continued from this quarantine packet.")).toBeVisible();
  await expect(page.getByText("Reconciled", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Proceed to reconciliation" })).toHaveCount(0);
});

test("quarantine details show type-specific review evidence", async ({ page }) => {
  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/quarantine")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: records.map(listItem), nextCursor: null, limit: 100, summary: { pending: 4, reprocessing: 2, resolved: 0, rejected: 1, overdue: 2, highPriority: 1 } }) });
      return;
    }
    if (request.method() === "GET") {
      const record = records.find((item) => url.pathname.endsWith(`/${item.id}`));
      if (record) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailItem(record)) });
        return;
      }
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ outcome: "OK" }) });
  });

  await page.goto("/review-center?tab=quarantine");
  await reviewButton(page, "DEMO-DUPLICATE-001").click();
  let dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Compare records" })).toBeVisible();
  const comparisonTable = dialog.getByRole("table", { name: "Incoming and existing transaction comparison" });
  await expect(comparisonTable).toContainText("99000");
  await expect(comparisonTable).toContainText("Timestamp");
  await expect(dialog).not.toContainText("fingerprint");
  await dialog.getByText("Close", { exact: true }).click();

  await reviewButton(page, "DEMO-ACCEPT-001").click();
  dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Exact duplicate", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("table", { name: "Incoming and existing transaction comparison" })).toContainText("Timestamp");
  await expect(dialog.getByRole("table", { name: "Incoming and existing transaction comparison" })).not.toContainText("Diff");
  await dialog.getByText("Close", { exact: true }).click();

  await reviewButton(page, "DEMO-INVALID-001").click();
  dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Required field evidence" })).toBeVisible();
  await expect(dialog.getByRole("table", { name: "Required field evidence" })).toContainText("MISSING");
  await expect(dialog.getByRole("table", { name: "Required field evidence" })).toContainText("Status");

  await dialog.getByText("Close", { exact: true }).click();
  await reviewButton(page, "DEMO-REJECT-001").click();
  dialog = page.getByRole("dialog");
  const sampleTable = dialog.getByRole("table", { name: "Sanitized sample row" });
  await expect(sampleTable).toContainText("Amount");
  await expect(sampleTable).toContainText("Missing");
});

test("stable API error codes are shown without leaking the response payload", async ({ page }) => {
  await page.route("**/api/v1/quarantine**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/quarantine")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [listItem(records[0])], nextCursor: null, limit: 100, summary: { pending: 4, reprocessing: 2, resolved: 0, rejected: 1, overdue: 2, highPriority: 1 } }) });
      return;
    }
    if (request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailItem(records[0])) });
      return;
    }
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: { outcome: "STALE_STATUS", errorCodes: ["STALE_STATUS"], reason: "The case changed before this action was applied." } }),
    });
  });

  await page.goto("/review-center?tab=quarantine");
  await page.getByLabel("Operator actor").fill("demo-operator");
  await reviewButton(page, "DEMO-INVALID-001").click();
  await page.getByRole("dialog").getByRole("button", { name: "Claim", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm claim", exact: true }).click();
  await expect(page.getByText("STALE_STATUS", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("DO-NOT-RENDER", { exact: true })).toHaveCount(0);
});
