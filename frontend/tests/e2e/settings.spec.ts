import { test, expect } from "./fixtures/auth";

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
    await expect(
      page.getByRole("button", { name: /Language: English/ }),
    ).toBeVisible({ timeout: 10000 });
  });

  // The language is stored on the account, and every spec signs in as the one
  // shared admin: saving "pl" for real would turn every spec that signs in
  // meanwhile Polish. The save is answered here instead; the request that
  // would store it is what the test reads.
  test("choosing a language saves it to the account and switches the interface", async ({
    page,
    authenticatedPage,
  }) => {
    const saved = page.waitForRequest(
      (request) =>
        request.url().endsWith("/api/v1/auth/me/language") &&
        request.method() === "POST",
    );
    await page.route("**/api/v1/auth/me/language", (route) =>
      route.fulfill({ json: { language: "pl" } }),
    );

    await page.getByRole("button", { name: /Language: English/ }).click();
    await page.getByRole("button", { name: "Polski", exact: true }).click();

    expect((await saved).postDataJSON()).toEqual({ language: "pl" });
    await expect(page.getByRole("button", { name: /^PL,/ })).toBeVisible({
      timeout: 15000,
    });
  });

  test("displays organization settings section", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByRole("textbox", { name: "Organization name" }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("displays modules settings/toggle", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/settings/modules");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(
      page.getByRole("heading", { level: 1, name: "Modules" }),
    ).toBeVisible({ timeout: 10000 });
    // Every module card carries its own switch: Deactivate while it is on.
    const toggleSwitch = page
      .getByRole("button", { name: /^(Deactivate|Activate) / })
      .first();
    await expect(toggleSwitch).toBeVisible({ timeout: 5000 });
  });

  test("saves settings without errors", async ({ page, authenticatedPage }) => {
    const name = page.getByRole("textbox", { name: "Organization name" });
    const original = await name.inputValue();
    const save = page.getByRole("button", { name: "Save" }).first();

    // The organization read after a save answers late here, as it does on a
    // loaded machine, so typing ahead of it is caught on every run.
    await page.route("**/api/v1/organizations/my", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });

    // Save stays off until a field changed: edit the name, save, put it back.
    await expect(save).toBeDisabled();
    await name.fill(`${original} edited`);
    await save.click();
    await expect(page.getByText("Organization settings saved")).toBeVisible({
      timeout: 10000,
    });
    // The saved name comes back from the server and refills the field; typing
    // before it has would be overwritten. The field already holds the typed
    // name, so it cannot tell. Save can: it stays on until the form matches
    // the organization as the server last answered it.
    await expect(save).toBeDisabled({ timeout: 10000 });
    await expect(
      page.locator('[role="alert"]').filter({ hasText: /error|failed/i }),
    ).toHaveCount(0);

    await name.fill(original);
    await expect(save).toBeEnabled();
    const restored = page.waitForResponse("**/api/v1/organizations/my");
    await save.click();
    expect((await restored).ok()).toBe(true);
    await expect(save).toBeDisabled({ timeout: 10000 });
  });

  test("navigates to API keys settings", async ({
    page,
    authenticatedPage,
  }) => {
    await page.getByRole("link", { name: "API Keys" }).click();
    await expect(page).toHaveURL(/\/settings\/api-keys/);
  });
});
