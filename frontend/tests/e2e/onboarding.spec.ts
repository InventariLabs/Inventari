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

    const hasHeading = await page
      .locator("h1, h2")
      .first()
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    const hasWizard = await page
      .locator(
        '[role="dialog"], form, div[class*="wizard"], div[class*="onboarding"]',
      )
      .first()
      .isVisible({ timeout: 10000 })
      .catch(() => false);

    expect(hasHeading || hasWizard).toBeTruthy();
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

    const actionBtn = page
      .getByRole("button", {
        name: /next|start|begin|dalej|zacznij|rozpocznij/i,
      })
      .first();
    const skipOrClose = page
      .getByRole("button", { name: /skip|pomiń|close|zamknij/i })
      .first();

    const hasAction = await actionBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    const hasSkip = await skipOrClose
      .isVisible({ timeout: 10000 })
      .catch(() => false);

    expect(hasAction || hasSkip).toBeTruthy();
  });
});
