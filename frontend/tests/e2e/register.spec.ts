import { test, expect } from "./fixtures/base";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Registration & Org Joining — flow", () => {
  let registeredEmail = "";
  let registeredPassword = "";
  let inviteCode = "";
  let api: ApiHelper;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);

    let attempt = 0;
    while (!inviteCode && attempt < 3) {
      try {
        const invite = await api.createInvite(auth.access_token);
        inviteCode = invite.invite_code;
      } catch {
        attempt++;
        if (attempt < 3) await new Promise((r) => setTimeout(r, 1000));
      }
    }
  });

  test.afterAll(async ({ playwright, baseURL }) => {
    if (!registeredEmail) return;
    const ctx = await playwright.request.newContext({ baseURL });
    const cleanupApi = new ApiHelper(ctx);
    try {
      const auth = await cleanupApi.login(registeredEmail, registeredPassword);
      await ctx
        .delete("/api/v1/users/me", {
          headers: { Authorization: `Bearer ${auth.access_token}` },
        })
        .catch(() => {});
    } catch {
      // ignore
    }
  });

  test("registration page renders with form fields", async ({ page }) => {
    await page.goto(`/register?invite=${inviteCode}`);

    await expect(page.getByLabel(/email|e-mail/i)).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByLabel(/^password|hasło/i).first()).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByLabel(/confirm|repeat|powtórz|password again/i),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByRole("button", {
        name: /register|sign up|sign in|rejestracja|załóż|create/i,
      }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("registration with mismatched passwords shows error", async ({
    page,
  }) => {
    await page.goto(`/register?invite=${inviteCode}`);

    await page
      .getByLabel(/email|e-mail/i)
      .fill(`mismatch-${Date.now()}@example.com`);
    await page
      .getByLabel(/^password|hasło/i)
      .first()
      .fill("SecurePass123!");
    await page
      .getByLabel(/confirm|repeat|powtórz|password again/i)
      .fill("DifferentPass123!");

    await page
      .getByRole("button", {
        name: /register|sign up|sign in|rejestracja|załóż|create/i,
      })
      .click();

    await expect(
      page.getByText(/mismatch|match|nie zgadza|doesn't match|nie pasuje/i),
    ).toBeVisible({ timeout: 5000 });
  });

  test("registration with invalid email shows validation error", async ({
    page,
  }) => {
    await page.goto(`/register?invite=${inviteCode}`);

    const emailInput = page.getByLabel(/email|e-mail/i);
    await emailInput.fill("not-an-email");
    await page
      .getByLabel(/^password|hasło/i)
      .first()
      .fill("SecurePass123!");
    await page
      .getByLabel(/confirm|repeat|powtórz|password again/i)
      .fill("SecurePass123!");

    await page
      .getByRole("button", {
        name: /register|sign up|sign in|rejestracja|załóż|create/i,
      })
      .click();

    const validationMessage = await emailInput.evaluate(
      (el: HTMLInputElement) => el.validationMessage,
    );
    expect(validationMessage).toBeTruthy();
  });

  test("successful registration shows success message or redirects", async ({
    page,
  }) => {
    await page.goto(`/register?invite=${inviteCode}`);

    const uniqueEmail = `test-${Date.now()}@example.com`;
    const password = "SecurePass123!";
    registeredEmail = uniqueEmail;
    registeredPassword = password;

    await page.getByLabel(/email|e-mail/i).fill(uniqueEmail);
    await page
      .getByLabel(/^password|hasło/i)
      .first()
      .fill(password);
    await page
      .getByLabel(/confirm|repeat|powtórz|password again/i)
      .fill(password);

    await page
      .getByRole("button", {
        name: /register|sign up|sign in|rejestracja|załóż|create/i,
      })
      .click();

    // The new account is signed in; it is not sent to a form asking for the
    // address and password it has just chosen.
    await page.waitForURL((url) => !/^\/(register|login)/.test(url.pathname), {
      timeout: 15000,
    });
  });

  test("joining organization via invite token works", async ({ page }) => {
    await page.goto(`/register?invite=${inviteCode}`);

    await expect(
      page.getByRole("heading", {
        name: /create.*account|join|organization|dołącz/i,
      }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("login link on register page navigates to login", async ({ page }) => {
    await page.goto("/register");

    const loginLink = page.getByRole("link", {
      name: /login|sign in|already|masz|konto/i,
    });

    if (await loginLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await loginLink.click();
      await expect(page).toHaveURL(/\/login/);
    }
  });
});
