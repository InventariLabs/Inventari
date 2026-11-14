import { devices } from "@playwright/test";
import { test, expect } from "./fixtures/auth";

test.describe("Responsive layout — mobile viewport", () => {
  test.use({ viewport: devices["iPhone SE"].viewport });

  test("login page is usable on mobile", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const emailInput = page.locator('input[type="email"], input[name="email"]');
    const passwordInput = page.locator('input[type="password"]');
    const submitBtn = page.getByRole("button", {
      name: /login|sign in|zaloguj/i,
    });

    await expect(emailInput).toBeVisible({ timeout: 15000 });
    await expect(passwordInput).toBeVisible({ timeout: 15000 });
    await expect(submitBtn).toBeVisible({ timeout: 15000 });
  });

  test("login form inputs are not cut off (within viewport)", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const submitBtn = page.getByRole("button", {
      name: /login|sign in|zaloguj/i,
    });
    await expect(submitBtn).toBeVisible({ timeout: 15000 });

    const box = await submitBtn.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x + box!.width).toBeLessThanOrEqual(375 + 20);
  });
});

// These tests run in the `mobile` project, which finishes before `module-gate`
// starts (Playwright runs the projects without dependencies first), so they do
// not race its assertions. globalSetup has already enabled every module.
test.describe("Responsive layout — authenticated pages", () => {
  test.use({ viewport: devices["iPhone SE"].viewport });

  test("items list is scrollable on mobile", async ({ page, authenticatedPage }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const content = page.locator('main, [role="main"], #root > div').first();
    await expect(content).toBeVisible({ timeout: 15000 });
    const overflow = await page.evaluate(
      () => document.body.scrollWidth > document.body.clientWidth,
    );
    expect(overflow).toBe(false);
  });

  test("module switcher opens on mobile", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});

    // The phone header has no hamburger: modules are reached from the switcher.
    const switcher = page.getByRole("button", { name: /Switch module/ });
    await expect(switcher).toBeVisible({ timeout: 10000 });
    await switcher.click();
    await expect(page.getByRole("menuitem", { name: "Warehouse" })).toBeVisible(
      { timeout: 5000 },
    );
  });

  test("adding a product opens a form that fits the phone", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const addBtn = page.getByRole("button", { name: "Add product" });
    await expect(addBtn).toBeVisible({ timeout: 10000 });
    await addBtn.click();

    await expect(
      page.getByRole("heading", { level: 1, name: "New Product" }),
    ).toBeVisible({ timeout: 10000 });
    const overflow = await page.evaluate(
      () => document.body.scrollWidth > document.body.clientWidth,
    );
    expect(overflow).toBe(false);
  });
});
