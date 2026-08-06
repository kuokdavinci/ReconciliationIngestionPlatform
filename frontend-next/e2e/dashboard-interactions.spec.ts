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
