import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  await page.route("https://fonts.gstatic.com/**", (route) => route.abort());
});

test("@requires-backend scheduler-first DEMO flow creates a Review Packet for operator review", async ({ page }) => {
  const schedulerRun = await page.request.post("/api/v1/automation/jobs/DEMO/run", {
    headers: { "X-Actor": "demo-operator" },
  });
  expect([200, 409]).toContain(schedulerRun.status());

  await expect.poll(async () => {
    const response = await page.request.get("/api/v1/review-packets?partner=DEMO");
    if (!response.ok()) return 0;
    const payload = await response.json() as { packets?: Array<{ status?: string; sourceType?: string }> };
    return (payload.packets ?? []).filter((packet) => packet.status === "PENDING" && packet.sourceType === "SCHEDULER_JOB").length;
  }, { timeout: 30_000 }).toBeGreaterThan(0);

  await page.goto("/review-center");
  await expect(page.getByText("Review Items", { exact: true })).toBeVisible();
  await expect(page.getByText(/settlement_DEMO_.*\.json/).first()).toBeVisible();
});
