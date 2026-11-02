import { cookieValue } from "../helpers/api";
import { test as base } from "./base";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./credentials";

/**
 * Auth fixture for the pl-PL project.
 *
 * The app takes its language from the signed-in user's `preferred_language`
 * (authStore calls i18n.changeLanguage with it on every load), so the browser
 * locale alone is not enough. Flipping that field on the shared
 * admin@example.com account would turn the English projects Polish mid-run —
 * they execute concurrently — so the profile response is patched per page
 * instead. Everything downstream is the real pipeline: authStore →
 * i18n.changeLanguage → rendered UI.
 */
export const test = base.extend<{
  polishPage: void;
}>({
  polishPage: async ({ request, page, baseURL }, use) => {
    const loginResp = await request.post("/api/v1/auth/login", {
      form: { username: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    if (!loginResp.ok()) {
      throw new Error(
        `Login failed: ${loginResp.status()} ${await loginResp.text()}`,
      );
    }
    const refreshToken = await cookieValue(request, "refresh_token");
    const cookieUrl = new URL(baseURL ?? "http://127.0.0.1:5173");

    await page.context().addCookies([
      {
        name: "refresh_token",
        value: refreshToken,
        url: cookieUrl.origin,
        httpOnly: true,
        secure: cookieUrl.protocol === "https:",
        sameSite: "Lax" as const,
      },
    ]);

    await page.route("**/api/v1/auth/me", async (route) => {
      const response = await route.fetch();
      if (!response.ok()) {
        await route.fulfill({ response });
        return;
      }
      const body = await response.json();
      await route.fulfill({
        response,
        json: { ...body, preferred_language: "pl" },
      });
    });

    await use();
  },
});

export { expect } from "@playwright/test";
