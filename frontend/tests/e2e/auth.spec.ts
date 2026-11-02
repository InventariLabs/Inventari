import { test, expect } from "./fixtures/base";

import { cookieValue } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Auth flow", () => {
  test("shows login form", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("#email")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("blocks login with invalid credentials", async ({ page }) => {
    await page.goto("/login");
    await page.fill("#email", "wrong@email.com");
    await page.fill("#password", "WrongPassword123!");
    await page.click('button[type="submit"]');

    // Should remain on login page and possibly show an error (handled by toast in this app)
    await expect(page).toHaveURL(/.*login/);
    // Optional: check for toast message if possible, but the URL check is a good start
  });

  test("logs in successfully and redirects to dashboard", async ({ page }) => {
    await page.goto("/login");

    await page.fill("#email", ADMIN_EMAIL);
    await page.fill("#password", ADMIN_PASSWORD);
    await page.click('button[type="submit"]');

    // The landing page is the Launcher unless the organization is in work
    // mode — assert we left /login, not a specific URL.
    await expect(page).not.toHaveURL(/.*login/, { timeout: 15000 });
  });

  test("logs out user", async ({ page }) => {
    // Perform login first
    await page.goto("/login");
    await page.fill("#email", ADMIN_EMAIL);
    await page.fill("#password", ADMIN_PASSWORD);
    await page.click('button[type="submit"]');

    // Wait until the post-login navigation finishes (target depends on
    // work mode).
    await expect(page).not.toHaveURL(/.*login/, { timeout: 15000 });

    // The logout button is inside a dropdown menu behind the user avatar.
    // Click the avatar first to open the dropdown.
    const avatarBtn = page.locator("[data-user-menu] button").first();
    await expect(avatarBtn).toBeVisible({ timeout: 5000 });
    await avatarBtn.click();

    // Now find the logout menuitem in the dropdown
    const logoutBtn = page.getByRole("menuitem", {
      name: /wyloguj|log out|logout/i,
    });
    await expect(logoutBtn).toBeVisible({ timeout: 5000 });
    await logoutBtn.click();

    await expect(page).toHaveURL(/.*login/);
  });

  test("lands home after signing back in, not on the page the session ended on", async ({
    page,
  }) => {
    // A shared device: the first account works on one address and signs out.
    // Whoever signs in next on this tab must not be handed that page —
    // PrivateRoute's `from` may only carry an address opened signed out.
    await page.goto("/login");
    await page.fill("#email", ADMIN_EMAIL);
    await page.fill("#password", ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    await expect(page).not.toHaveURL(/.*login/, { timeout: 15000 });

    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings/);

    const avatarBtn = page.locator("[data-user-menu] button").first();
    await expect(avatarBtn).toBeVisible({ timeout: 5000 });
    await avatarBtn.click();
    const logoutBtn = page.getByRole("menuitem", {
      name: /wyloguj|log out|logout/i,
    });
    await expect(logoutBtn).toBeVisible({ timeout: 5000 });
    await logoutBtn.click();
    await expect(page).toHaveURL(/.*login/);

    // The sign-in has nowhere to continue to: nothing was asked for while
    // signed out, so it goes home — wherever the profile's home is.
    await page.fill("#email", ADMIN_EMAIL);
    await page.fill("#password", ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    await expect(page).not.toHaveURL(/.*login/, { timeout: 15000 });
    expect(new URL(page.url()).pathname).not.toBe("/settings");
  });

  test("redirects to login when accessing protected route without session", async ({
    page,
  }) => {
    // Clear any existing state just in case
    await page.context().clearCookies();

    // Attempt to directly visit a protected route
    await page.goto("/items");

    // Should immediately redirect to login page
    await expect(page).toHaveURL(/.*login/);

    // Verify an element from the login page is visible (not just URL change)
    await expect(page.locator("#email")).toBeVisible();
  });

  test("persists session across page reloads", async ({
    page,
    request,
    baseURL,
  }) => {
    const loginResp = await request.post("/api/v1/auth/login", {
      form: {
        username: ADMIN_EMAIL,
        password: ADMIN_PASSWORD,
      },
    });
    expect(loginResp.ok()).toBeTruthy();

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

    await page.goto("/");
    // `/` may redirect to the focused module in work mode —
    // assert only that the session is authenticated (not bounced to /login).
    await expect(page).not.toHaveURL(/.*login/, { timeout: 15000 });

    // Reload the page
    await page.reload();

    // Given the JWT/cookie is still valid, we should NOT be kicked back to login
    await expect(page).not.toHaveURL(/.*login/, { timeout: 10000 });
    await expect(page.locator("#email")).not.toBeVisible();
  });
});
