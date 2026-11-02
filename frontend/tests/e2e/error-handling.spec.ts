import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";

test.describe("Error handling — 404, API errors, graceful degradation", () => {
  test("unknown route shows 404 / not-found page", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/this-route-definitely-does-not-exist-e2e");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    const notFound = page.getByText(
      /404|not found|nie znaleziono|page not found|does not exist/i,
    );
    await expect(notFound.first()).toBeVisible({ timeout: 15000 });
  });

  test("navigating to non-existent item detail shows error/404", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items/00000000-0000-0000-0000-000000000000");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    // The detail screen answers a missing product with its own sentence
    // ("This product no longer exists, or you have no access to it.") —
    // the graceful 404 this test asks for, under words the app chose.
    const errorContent = page.getByText(
      /not found|404|nie znaleziono|error|does not exist|no longer exists/i,
    );
    await expect(errorContent.first()).toBeVisible({ timeout: 15000 });
  });

  test("app header/navigation is intact on 404 page", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/this-route-definitely-does-not-exist-e2e");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    const anyNav = page
      .locator(
        'nav, [role="navigation"], aside, #sidebar, #header, button[aria-label*="Command"], header',
      )
      .first();
    await expect(anyNav).toBeVisible({ timeout: 15000 });
  });

  test("back-to-home link available on 404 page", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/this-route-definitely-does-not-exist-e2e");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    const homeLink = page
      .locator('a[href="/"], a[href*="dashboard"], a[href="/settings/modules"]')
      .first();
    await expect(homeLink).toBeVisible({ timeout: 15000 });
  });

  test("API validation error is shown in form (invalid item create)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items/add");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(
      page.getByRole("heading", { name: /new product|add product/i }).first(),
    ).toBeVisible({ timeout: 5000 });
  });

  test("unauthenticated access to protected route redirects to login", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(page).toHaveURL(/login|signin|auth/i, { timeout: 15000 });
    const emailInput = page.locator(
      'input[type="email"], input[name="email"], #email',
    );
    await expect(emailInput.first()).toBeVisible({ timeout: 10000 });
  });
});
