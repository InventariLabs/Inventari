import { test, expect } from "./fixtures/auth";

test.describe("Dashboard — overview & widgets", () => {
  test.beforeEach(async ({ page, authenticatedPage }) => {
    // `/` redirects to the focused module in work mode, so Launcher
    // assertions target the stable `/launcher` URL directly.
    await page.goto("/launcher");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("dashboard page loads after login", async ({
    page,
    authenticatedPage,
  }) => {
    // The launcher greets the signed-in user by name in its only <h1>. A
    // text match on /home/ also hit a module description hidden on phones.
    await expect(
      page.getByRole("heading", { level: 1, name: /^Welcome, / }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("displays module navigation cards", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.locator("#launcher-modules-heading")).toBeAttached({
      timeout: 10000,
    });
    const anyModule = page
      .getByRole("link", { name: /Inventory|Equipment|Recipes/i })
      .first();
    await expect(anyModule).toBeVisible({ timeout: 5000 });
  });

  test("modules section shows essentials and business groups", async ({
    page,
    authenticatedPage,
  }) => {
    const isMobile =
      page.viewportSize()?.width && page.viewportSize()!.width < 768;
    if (isMobile) {
      const anyModule = page
        .getByRole("link", { name: /Inventory|Equipment|Recipes/i })
        .first();
      await expect(anyModule).toBeVisible({ timeout: 10000 });
    } else {
      await expect(
        page.getByRole("heading", { name: /essentials/i }),
      ).toBeVisible({
        timeout: 5000,
      });
      await expect(
        page.getByRole("heading", { name: /business/i }),
      ).toBeVisible({
        timeout: 5000,
      });
    }
  });

  test("clicking Inventory navigates to items", async ({
    page,
    authenticatedPage,
  }) => {
    const inventoryLink = page
      .getByRole("link", { name: /Inventory/i })
      .first();
    await expect(inventoryLink).toBeVisible({ timeout: 10000 });
    await inventoryLink.click();
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await expect(page).toHaveURL(/\/inventory/);
    await expect(page.locator("main#main-content")).toBeVisible({
      timeout: 10000,
    });
  });

  test("clicking Settings navigates to settings", async ({
    page,
    authenticatedPage,
  }) => {
    const settingsLink = page.getByRole("link", { name: /Settings/i }).first();
    await expect(settingsLink).toBeVisible({ timeout: 10000 });
    await settingsLink.click();
    await expect(page).toHaveURL(/\/settings/);
  });

  test("inventory dashboard page loads from launcher", async ({
    page,
    authenticatedPage,
  }) => {
    const inventoryLink = page
      .getByRole("link", { name: /Inventory/i })
      .first();
    await expect(inventoryLink).toBeVisible({ timeout: 10000 });
    await inventoryLink.click();
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    const anyContent = page.locator("main#main-content");
    await expect(anyContent).toBeVisible({ timeout: 15000 });
  });

  test("clicking Shopping Lists navigates to shopping-lists", async ({
    page,
  }) => {
    const slLink = page.getByRole("link", { name: /Shopping Lists/i }).first();
    await expect(slLink).toBeVisible({ timeout: 10000 });
    await slLink.click();
    await expect(page).toHaveURL(/\/shopping-lists/);
  });
});
