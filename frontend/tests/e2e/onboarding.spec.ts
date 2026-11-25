import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";

// globalSetup completes onboarding, and a finished org is redirected away from
// /onboarding, so the wizard is shown by reporting this org as not onboarded.
async function showWizard(page: Page) {
  await page.route("**/api/v1/organizations/my", (route) =>
    route.fulfill({ json: { id: "org-e2e", onboarding_completed: false } }),
  );
}

test.describe("Onboarding — setup wizard", () => {
  test("onboarding page loads without error", async ({
    page,
    authenticatedPage,
  }) => {
    await showWizard(page);
    await page.goto("/onboarding");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await page
      .locator("h1, h2")
      .first()
      .waitFor({ state: "visible", timeout: 10000 })
      .catch(() => {});

    await expect(page).toHaveURL(/\/onboarding/);

    await expect(
      page.getByRole("heading", { name: "Choose your workspace mode" }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("onboarding page has next/start action", async ({
    page,
    authenticatedPage,
  }) => {
    await showWizard(page);
    await page.goto("/onboarding");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await page
      .locator("h1, h2")
      .first()
      .waitFor({ state: "visible", timeout: 10000 })
      .catch(() => {});

    await expect(page).toHaveURL(/\/onboarding/);

    await expect(page.getByRole("button", { name: "Get started" })).toBeVisible(
      { timeout: 10000 },
    );
  });
});
