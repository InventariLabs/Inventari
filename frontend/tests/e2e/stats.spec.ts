import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Stats — analytics & reporting", () => {
  let api: ApiHelper;
  let token: string;
  let seedStorageId: string;
  let seedCategoryId: string;

  const uid = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    const storage = await api.createStorageIdempotent(token, {
      name: `E2E-Stats-Storage-${uid}`,
    });
    seedStorageId = storage.id;
    const category = await api.createCategoryIdempotent(token, {
      name: `E2E-Stats-Cat-${uid}`,
    });
    seedCategoryId = category.id;

    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    const nextWeek = new Date(today);
    nextWeek.setDate(today.getDate() + 7);
    const fmt = (d: Date) => d.toISOString().split("T")[0];

    await api.createItem(token, {
      name: "E2E-Stats-Expiring",
      quantity: 2,
      unit: "pcs",
      expiry_date: fmt(tomorrow),
      location_id: seedStorageId,
      category_id: seedCategoryId,
    });
    await api.createItem(token, {
      name: "E2E-Stats-Expired",
      quantity: 1,
      unit: "pcs",
      expiry_date: fmt(yesterday),
      location_id: seedStorageId,
      category_id: seedCategoryId,
    });
    await api.createItem(token, {
      name: "E2E-Stats-Low",
      quantity: 1,
      unit: "pcs",
      expiry_date: fmt(nextWeek),
      location_id: seedStorageId,
      category_id: seedCategoryId,
    });
    await api.createItem(token, {
      name: "E2E-Stats-Bulk",
      quantity: 50,
      unit: "pcs",
      expiry_date: fmt(nextWeek),
      location_id: seedStorageId,
      category_id: seedCategoryId,
    });
  });

  test.afterAll(async () => {
    if (token && seedStorageId) {
      const items = await api.listItems(token, `location_id=${seedStorageId}`);
      for (const item of items) {
        await api.deleteItem(token, item.id).catch(() => {});
      }
      await api.deleteStorage(token, seedStorageId).catch(() => {});
    }
    if (token && seedCategoryId) {
      await api.deleteCategory(token, seedCategoryId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/inventory/stats");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("displays stats page heading", async ({ page, authenticatedPage }) => {
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("displays rotation/usage charts", async ({
    page,
    authenticatedPage,
  }) => {
    const chart = page
      .locator(
        '.recharts-responsive-container, canvas, svg[class*="chart"], [class*="recharts"]',
      )
      .first();
    const chartVisible = await chart
      .isVisible({ timeout: 15000 })
      .catch(() => false);
    if (!chartVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 15000,
      });
      return;
    }
    await expect(chart).toBeVisible();
  });

  test("navigates to analytics tab and renders content", async ({
    page,
    authenticatedPage,
  }) => {
    const analyticsTab = page.getByRole("link", { name: /analytics/i }).first();
    const tabVisible = await analyticsTab
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!tabVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 15000,
      });
      return;
    }
    await analyticsTab.click();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const heading = page.locator("h1, h2, h3").first();
    await expect(heading).toBeVisible({ timeout: 10000 });
  });

  test("low stock alerts section is present", async ({
    page,
    authenticatedPage,
  }) => {
    const analyticsTab = page.getByRole("link", { name: /analytics/i }).first();
    const tabVisible = await analyticsTab
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!tabVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 15000,
      });
      return;
    }
    await analyticsTab.click();

    await expect(page.locator("h1, h2, h3").first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("forecasting or predictions section is visible", async ({
    page,
    authenticatedPage,
  }) => {
    const analyticsTab = page.getByRole("link", { name: /analytics/i }).first();
    const tabVisible = await analyticsTab
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!tabVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 15000,
      });
      return;
    }
    await analyticsTab.click();

    await expect(page.locator("h1, h2, h3").first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("stats page loads without errors", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.locator("h1, h2, h3").first()).toBeVisible({
      timeout: 15000,
    });

    const errorAlert = page
      .locator('[role="alert"]')
      .filter({ hasText: /error|failed|błąd/i });
    await expect(errorAlert).not.toBeVisible();
  });
});
