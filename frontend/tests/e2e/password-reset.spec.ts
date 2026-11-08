import { randomUUID } from "node:crypto";
import type { PlaywrightWorkerArgs } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Password reset end-to-end.
 *
 * IMPORTANT — test isolation:
 * This spec creates its OWN dedicated test user (via invite + register) and
 * resets THAT user's password. It must NEVER mutate the shared
 * ``admin@example.com`` / ``Admin123`` credentials that every other spec
 * logs in with — doing so causes a 401 cascade in parallel workers during
 * the mutation window.
 *
 * The dev SMTP transport is not configured in the test environment, so the
 * reset email never lands. To still drive the full UI flow we use a
 * testing-only debug endpoint (``POST /auth/password-reset/_dev_token``,
 * guarded by ``settings.TESTING``) to mint a token for the dedicated user,
 * then walk through:
 *   1. ``/forgot-password`` UI submits the email.
 *   2. ``/reset-password/:token`` UI sets a new password.
 *   3. The login API accepts the new password.
 */
const INITIAL_PASSWORD = "ResetMe123!";
const NEW_PASSWORD = "ResetMe123!New!";

interface DedicatedUser {
  email: string;
  id: string;
}

/**
 * Register a throwaway user for ONE test. Each test gets its own address
 * (random, not a timestamp: two workers can start in the same millisecond)
 * and its own password history, so the order and the number of workers
 * cannot change what a test finds.
 */
async function createDedicatedUser(
  playwright: PlaywrightWorkerArgs["playwright"],
  baseURL: string | undefined,
): Promise<DedicatedUser> {
  const ctx = await playwright.request.newContext({ baseURL });
  try {
    const api = new ApiHelper(ctx);
    // Admin creates an invite and registers a user whose password the test
    // is allowed to mutate.
    const adminAuth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const email = `pwreset-e2e-${randomUUID()}@example.com`;
    const { invite_code } = await api.createInvite(
      adminAuth.access_token,
      email,
    );
    const registerResp = await ctx.post("/api/v1/auth/register", {
      data: { email, password: INITIAL_PASSWORD, invite_code },
    });
    if (!registerResp.ok()) {
      throw new Error(
        `Failed to register dedicated password-reset user: ${registerResp.status()} ${await registerResp.text()}`,
      );
    }
    const userAuth = await api.login(email, INITIAL_PASSWORD);
    const me = await ctx.get("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${userAuth.access_token}` },
    });
    return { email, id: (await me.json()).id };
  } finally {
    await ctx.dispose();
  }
}

async function removeDedicatedUser(
  playwright: PlaywrightWorkerArgs["playwright"],
  baseURL: string | undefined,
  user: DedicatedUser | undefined,
): Promise<void> {
  if (!user) return;
  const ctx = await playwright.request.newContext({ baseURL });
  try {
    const api = new ApiHelper(ctx);
    const adminAuth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    await ctx.post(`/api/v1/organizations/my/remove-member/${user.id}`, {
      headers: { Authorization: `Bearer ${adminAuth.access_token}` },
    });
  } catch {
    // Best-effort cleanup — a leftover test user is harmless.
  } finally {
    await ctx.dispose();
  }
}

test.describe("Password reset flow", () => {
  // Per test, not per worker: the tests change the same kind of state
  // (a password) and must not share the account that holds it.
  let user: DedicatedUser | undefined;

  test.beforeEach(async ({ playwright, baseURL }) => {
    user = await createDedicatedUser(playwright, baseURL);
  });

  const dedicatedEmail = (): string => {
    if (!user) throw new Error("dedicated password-reset user not created");
    return user.email;
  };

  test.afterEach(async ({ playwright, baseURL }) => {
    await removeDedicatedUser(playwright, baseURL, user);
    user = undefined;
  });

  test("request → confirm → login with the rotated password", async ({
    playwright,
    baseURL,
    page,
  }) => {
    // 1. Visit the forgot-password page and submit the dedicated user's email.
    await page.goto("/forgot-password");
    await expect(
      page.getByRole("heading", { name: /forgot|reset/i }).first(),
    ).toBeVisible({ timeout: 10000 });
    await page.fill("#email", dedicatedEmail());
    await page.click('button[type="submit"]');

    // The form should advance to a success state (data-testid on the page).
    await expect(page.getByTestId("forgot-success")).toBeVisible({
      timeout: 10000,
    });

    // 2. Mint a token for the dedicated user via the testing-only endpoint.
    //    The _dev_token route is only registered when the backend runs with
    //    TESTING=true (it cannot exist in production). CI sets it, and
    //    `make test-e2e` (which `make test-e2e-isolated` runs on dev2)
    //    restarts the backend with it for the run, so a 404 here is a stack
    //    started some other way: a failure that says so, not a skip that
    //    would hide the reset flow going untested.
    const ctx = await playwright.request.newContext({ baseURL });
    const issue = await ctx.post("/api/v1/auth/password-reset/_dev_token", {
      data: { email: dedicatedEmail() },
    });
    expect(
      issue.status(),
      "_dev_token route unavailable — the backend must run with TESTING=true (make test-e2e does it)",
    ).toBe(200);
    const { token: resetToken } = await issue.json();
    expect(resetToken).toBeTruthy();

    // 3. Open the reset-password page with the token and submit a new pwd.
    await page.goto(`/reset-password/${resetToken}`);
    await expect(
      page.getByRole("heading", { name: /reset|forgot/i }).first(),
    ).toBeVisible({ timeout: 10000 });
    await page.fill("#new-password", NEW_PASSWORD);
    await page.fill("#confirm-password", NEW_PASSWORD);
    await page.click('button[type="submit"]');

    // The form should advance to a success state.
    await expect(page.getByTestId("reset-success")).toBeVisible({
      timeout: 10000,
    });

    // 4. Verify login with the new password works through the API.
    const apiCtx = await playwright.request.newContext({ baseURL });
    const api = new ApiHelper(apiCtx);
    const loginResp = await api.login(dedicatedEmail(), NEW_PASSWORD);
    expect(loginResp.access_token).toBeTruthy();
    await apiCtx.dispose();
    await ctx.dispose();
  });

  test("a dead link is refused when the page opens, and the password does not change", async ({
    playwright,
    baseURL,
    page,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const api = new ApiHelper(ctx);

    // Initial password still works before the bad-reset attempt.
    const before = await api.login(dedicatedEmail(), INITIAL_PASSWORD);
    expect(before.access_token).toBeTruthy();

    // The page asks before it shows a form, so nobody types a password the
    // link can never save. The server gives a spent, an expired and a forged
    // token one and the same refusal (the API tests hold it to that), so a
    // forged token stands in for the spent one here: this backend runs with
    // TESTING=true, which starts without the Redis store that remembers a
    // spent token, and a spent one would still be accepted.
    await page.goto("/reset-password/forged.invalid.token");
    const refusal = page.getByTestId("reset-invalid-link");
    await expect(refusal).toBeVisible({ timeout: 10000 });
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await expect(refusal.locator('a[href="/forgot-password"]')).toBeVisible();

    // Try to confirm with a forged token — should be 400.
    const res = await ctx.post("/api/v1/auth/password-reset/confirm", {
      data: { token: "forged.invalid.token", new_password: NEW_PASSWORD },
    });
    expect(res.status()).toBe(400);

    // Initial password is still valid.
    const after = await api.login(dedicatedEmail(), INITIAL_PASSWORD);
    expect(after.access_token).toBeTruthy();
    await ctx.dispose();
  });
});
