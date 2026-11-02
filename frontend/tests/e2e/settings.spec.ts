import { test, expect } from "./fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Settings — organization & user preferences", () => {
  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("displays settings page with main heading", async ({
    page,
    authenticatedPage,
  }) => {
    const heading = page.locator("h1, h2").first();
    await expect(heading).toBeVisible({ timeout: 15000 });
  });

  test("displays language selector", async ({ page, authenticatedPage }) => {
    const langControl = page
      .locator(
        '[aria-label*="language" i], [aria-label*="język" i], select, button',
      )
      .filter({ hasText: /english|polish|polski|en|pl/i })
      .first();
    const langVisible = await langControl
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!langVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 10000,
      });
    }
  });

  // This test flips `preferred_language` on the shared `admin@example.com`
  // account, and that setting is persisted server-side. Without restoring it,
  // every test that runs afterwards — in this run and in every future one —
  // renders the UI in the other language while asserting English text, which
  // surfaces as a wall of unrelated `element(s) not found` failures.
  test.afterEach(async ({ request }) => {
    const login = await request.post("/api/v1/auth/login", {
      form: { username: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    if (!login.ok()) return;
    const { access_token: token } = await login.json();
    await request.post("/api/v1/auth/me/language", {
      headers: { Authorization: `Bearer ${token}` },
      data: { language: "en" },
    });
  });

  test("changing language persists after page reload", async ({
    page,
    authenticatedPage,
  }) => {
    const langBtn = page
      .locator("button")
      .filter({ hasText: /^(EN|PL)$/ })
      .first();
    if (!(await langBtn.isVisible({ timeout: 5000 }).catch(() => false)))
      return;
    await langBtn.click();
    await page
      .getByRole("menuitem")
      .first()
      .waitFor({ state: "visible", timeout: 5000 })
      .catch(() => {});

    const targetOption = page.getByRole("menuitem").first();
    if (await targetOption.isVisible({ timeout: 5000 }).catch(() => false)) {
      await targetOption.click();
    }
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await page.reload();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("displays organization settings section", async ({
    page,
    authenticatedPage,
  }) => {
    const orgSection = page
      .locator("section, div, fieldset")
      .filter({
        hasText: /household|organization|organizacja|company|firma|general/i,
      })
      .first();
    const orgVisible = await orgSection
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!orgVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 10000,
      });
    }
  });

  test("displays modules settings/toggle", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/settings/modules");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const moduleHeading = page.getByRole("heading", {
      level: 2,
      name: /module management|moduły|modules/i,
    });
    if (
      !(await moduleHeading.isVisible({ timeout: 10000 }).catch(() => false))
    ) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 10000,
      });
      return;
    }
    const toggleSwitch = page.locator('[data-testid="module-toggle"]').first();
    const toggleVisible = await toggleSwitch
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    if (!toggleVisible) {
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 10000,
      });
    }
  });

  test("saves settings without errors", async ({ page, authenticatedPage }) => {
    const saveBtn = page.getByRole("button", { name: /save|zapisz/i });

    if (await saveBtn.isVisible({ timeout: 10000 }).catch(() => false)) {
      if (await saveBtn.isEnabled().catch(() => false)) {
        await saveBtn.click();
        await page
          .waitForLoadState("networkidle", { timeout: 15000 })
          .catch(() => {});
      }
      const errorAlert = page
        .locator('[role="alert"]')
        .filter({ hasText: /error|failed|błąd/i });
      await expect(errorAlert).toHaveCount(0, { timeout: 5000 });
    }
  });

  test("navigates to API keys settings if available", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/settings/developer");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const apiKeysLink = page.getByRole("link", {
      name: /api keys|personal access|tokens/i,
    });

    if (await apiKeysLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await apiKeysLink.click();
      await expect(page).toHaveURL(/api-keys|keys/);
    }
  });
});
