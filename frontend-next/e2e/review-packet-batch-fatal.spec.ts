import { expect, test } from "@playwright/test";

const packet = {
  _id: "packet-batch-fatal",
  partner: "DEMO",
  fileName: "demo-missing-column.csv",
  fileTypeDetected: "SETTLEMENT",
  status: "APPROVED",
  validationGates: [{ gateKey: "runtime_validation", status: "pass", label: "Runtime validation" }],
  riskSummary: { severity: "high" },
  recommendedAction: { actionType: "APPROVE", reason: "Approved mapping requires post-approval processing." },
  parseStrategy: { sheetName: "Sheet1", startRow: 2, fieldMappingCount: 4 },
  qualityGateStatus: "FAIL",
  qualityGateSummary: {
    outcome: "BATCH_FATAL",
    errorCodes: ["MISSING_REQUIRED_SOURCE_COLUMN"],
    totalRows: 10,
    failedRows: 10,
    activeRows: 0,
  },
  createdAt: "2026-08-28T03:00:00Z",
};

const run = {
  id: "post-run-batch-fatal",
  packetId: packet._id,
  partner: "DEMO",
  status: "FAILED",
  qualityGateStatus: "FAIL",
  qualityGateSummary: packet.qualityGateSummary,
  stage: "ingestion",
  message: "Post-approval quality gate failed before reconciliation.",
  stats: { totalRows: 10, successRows: 0, failedRows: 10 },
  errors: [],
  createdAt: "2026-08-28T03:00:00Z",
  updatedAt: "2026-08-28T03:01:00Z",
};

test("batch fatal remains visible on the parent review packet", async ({ page }) => {
  await page.route("**/api/v1/review-packets**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/post-approve-run")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run }) });
      return;
    }
    if (url.pathname.endsWith(`/${packet._id}`)) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ packet }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ packets: [packet] }) });
  });

  await page.goto("/review-center");
  const reviewMain = page.locator("main");
  await expect(reviewMain.getByText("BATCH FATAL", { exact: true }).first()).toBeVisible();
  await expect(reviewMain.getByText("MISSING_REQUIRED_SOURCE_COLUMN", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "View batch failure" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("BATCH FATAL");
  await expect(dialog).toContainText("No row-level quarantine was created");
  await expect(dialog).toContainText("MISSING_REQUIRED_SOURCE_COLUMN");
  await expect(dialog).not.toHaveText(/Open quarantine review/);

  await dialog.getByText("Close", { exact: true }).click();
  await expect(reviewMain.getByText("BATCH FATAL", { exact: true }).first()).toBeVisible();
});
