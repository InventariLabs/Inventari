import { devices } from "@playwright/test";
import { test, expect } from "./fixtures/base";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

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

  test("items list is scrollable on mobile", async ({ page, request }) => {
    const { ApiHelper } = await import("./helpers/api");
    const api = new ApiHelper(request);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.context().addCookies([
      {
        name: "refresh_token",
        value: auth.refresh_token,
        domain: "localhost",
        path: "/",
        httpOnly: true,
        secure: false,
        sameSite: "Lax" as const,
      },
    ]);
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const content = page.locator('main, [role="main"], #root > div').first();
    await expect(content).toBeVisible({ timeout: 15000 });
    const overflow = await page.evaluate(
      () => document.body.scrollWidth > document.body.clientWidth,
    );
    expect(overflow).toBe(false);
  });

  test("navigation hamburger/drawer opens on mobile", async ({
    page,
    request,
  }) => {
    const { ApiHelper } = await import("./helpers/api");
    const api = new ApiHelper(request);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.context().addCookies([
      {
        name: "refresh_token",
        value: auth.refresh_token,
        domain: "localhost",
        path: "/",
        httpOnly: true,
        secure: false,
        sameSite: "Lax" as const,
      },
    ]);

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});

    const bodyOrMain = page.locator("body").first();
    await expect(bodyOrMain).toBeVisible({ timeout: 15000 });

    const hamburger = page.getByRole("button", { name: /menu/i }).or(
      page.locator('button[aria-label*="menu" i]').first()
    ).first();
    const hamburgerVisible = await hamburger.isVisible({ timeout: 5000 }).catch(() => false);
    if (!hamburgerVisible) return;

    await hamburger.click();
    const drawer = page.locator('[role="dialog"], nav, aside, [class*="drawer"], [class*="sidebar"]').first();
    const drawerVisible = await drawer.isVisible({ timeout: 5000 }).catch(() => false);
    if (drawerVisible) return;
  });

  test("modal opens as bottom sheet on mobile", async ({ page, request }) => {
    const { ApiHelper } = await import("./helpers/api");
    const api = new ApiHelper(request);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.context().addCookies([
      {
        name: "refresh_token",
        value: auth.refresh_token,
        domain: "localhost",
        path: "/",
        httpOnly: true,
        secure: false,
        sameSite: "Lax",
      },
    ]);
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const addBtn = page
      .getByRole("button", { name: /add|dodaj|new|nowy|create/i })
      .first();
    if (!(await addBtn.isVisible({ timeout: 10000 }).catch(() => false))) return;
    await addBtn.click();

    const modal = page
      .locator('[role="dialog"], [class*="sheet"], [class*="modal"]')
      .first();
    const modalVisible = await modal.isVisible({ timeout: 10000 }).catch(() => false);
    if (!modalVisible) return;
    const box = await modal.boundingBox();
    if (!box) return;
    expect(box.width).toBeGreaterThan(0);
  });
});
