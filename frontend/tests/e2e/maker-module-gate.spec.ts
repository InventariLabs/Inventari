import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — the module gate.
 *
 * Switching a module off is an org-wide write, and every worker shares the one
 * test organization. While maker is off, every maker endpoint answers 403 to
 * every spec in flight: another worker's production list stays on "Loading
 * orders…" while the query retries, and the dashboard's result widget never
 * renders. So these tests run in the `module-gate` project, after every
 * `chromium` spec (playwright.config.ts), one after another, and each switches
 * maker back on before it ends.
 */

test.describe.configure({ mode: "serial" });

test.describe("Maker — module gate", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    // A known starting state, whatever an interrupted run left behind.
    await api.toggleModule(token, "maker", true);
  });

  test.afterAll(async () => {
    await api.toggleModule(token, "maker", true);
    await ctx.dispose();
  });

  test("disabling the module returns 403 on maker endpoints", async () => {
    await api.toggleModule(token, "maker", false);
    try {
      const response = await ctx.get("/api/v1/maker/production/orders", {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(response.status()).toBe(403);
    } finally {
      await api.toggleModule(token, "maker", true);
    }
  });

  test("disabling maker hides the launch card from the module launcher", async ({
    page,
    authenticatedPage,
  }) => {
    await api.toggleModule(token, "maker", false);
    try {
      // `/` redirects in work mode — the Launcher's stable URL is /launcher.
      await page.goto("/launcher");
      await page
        .waitForLoadState("networkidle", { timeout: 15000 })
        .catch(() => {});
      const launcherCard = page.getByText(/^Maker$/i).first();
      const present = await launcherCard
        .isVisible({ timeout: 3000 })
        .catch(() => false);
      expect(present).toBe(false);
    } finally {
      await api.toggleModule(token, "maker", true);
    }
  });
});
