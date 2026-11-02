import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe.configure({ mode: "serial" });

test.describe("API Keys — CRUD flow", () => {
  let api: ApiHelper;
  let token: string;
  let listKeyId: string | null = null;
  let listKeyName: string | null = null;
  let revokeKeyId: string | null = null;
  let revokeKeyName: string | null = null;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const existingKeys = await api.listApiKeys(token);
    for (const k of existingKeys) {
      if (k.name.startsWith("Test API Key")) {
        await api.deleteApiKey(token, k.id).catch(() => {});
      }
    }

    listKeyName = `Test API Key ${Date.now()}-list`;
    const listKey = await api.createApiKey(token, { name: listKeyName });
    listKeyId = listKey.id;

    revokeKeyName = `Test API Key ${Date.now()}-revoke`;
    const revokeKey = await api.createApiKey(token, { name: revokeKeyName });
    revokeKeyId = revokeKey.id;
  });

  test.afterAll(async () => {
    if (token && listKeyId) {
      await api.deleteApiKey(token, listKeyId).catch(() => {});
    }
    if (token && revokeKeyId) {
      await api.deleteApiKey(token, revokeKeyId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/settings/api-keys");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("displays api-keys page heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: /api keys/i }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("opens create key form and cancels", async ({
    page,
    authenticatedPage,
  }) => {
    const generateBtn = page.getByRole("button", { name: /generate new key/i });
    await expect(generateBtn).toBeVisible({ timeout: 10000 });
    await generateBtn.click();

    await expect(
      page.getByRole("heading", { name: /generate new api key/i }),
    ).toBeVisible({ timeout: 10000 });

    const nameInput = page.getByRole("textbox", { name: /^name$/i });
    await nameInput.click();
    await nameInput.pressSequentially(`TestKey${Date.now()}`);

    const submitBtn = page.getByRole("button", { name: /generate key/i });
    await expect(submitBtn).toBeVisible({ timeout: 5000 });

    const cancelBtn = page.getByRole("button", { name: /cancel/i });
    await cancelBtn.click();
    await expect(
      page.getByRole("heading", { name: /generate new api key/i }),
    ).not.toBeVisible({ timeout: 5000 });
  });

  test("the key-purpose select shows its whole label on a phone", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: /generate new key/i }).click();
    const select = page.getByRole("combobox", { name: /what the key is for/i });
    await expect(select).toBeVisible({ timeout: 10000 });

    // A native select clips its text at the chevron without telling anyone, so
    // the text is measured with the select's own font against the room left
    // between its padding.
    const { needed, room } = await select.evaluate((el: HTMLSelectElement) => {
      const style = getComputedStyle(el);
      const canvas = document.createElement("canvas").getContext("2d")!;
      canvas.font = style.font;
      const text = el.selectedOptions[0].textContent ?? "";
      return {
        needed: canvas.measureText(text).width,
        room:
          el.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight),
      };
    });
    expect(needed).toBeLessThanOrEqual(room);
  });

  test("a new ordinary key starts with read permissions only", async ({
    page,
    authenticatedPage,
  }) => {
    await page.getByRole("button", { name: /generate new key/i }).click();
    const group = page.getByRole("group", { name: /what the key may do/i });
    await expect(group).toBeVisible({ timeout: 10000 });

    const ticked = await group.getByRole("checkbox", { checked: true }).all();
    expect(ticked.length).toBeGreaterThan(0);
    for (const box of ticked) {
      await expect(box).toHaveAccessibleName(/^(?!.*(add|change|delete)).*$/i);
    }
    await expect(group.getByText(/starts read-only/i)).toBeVisible();
  });

  test("lists created API key in the table", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: /api keys/i }),
    ).toBeVisible({ timeout: 15000 });

    if (!listKeyName) return;
    const row = page
      .getByRole("row")
      .filter({ hasText: listKeyName })
      .first();
    await expect(row).toBeVisible({ timeout: 10000 });
  });

  test("revokes (deletes) an API key from the table", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: /api keys/i }),
    ).toBeVisible({ timeout: 15000 });

    if (!revokeKeyName) return;
    const row = page
      .getByRole("row")
      .filter({ hasText: revokeKeyName })
      .first();
    await expect(row).toBeVisible({ timeout: 10000 });

    const deleteBtn = row.getByRole("button", { name: /revoke/i }).first();
    await expect(deleteBtn).toBeVisible({ timeout: 5000 });
    await deleteBtn.click();

    const confirmBtn = page
      .getByRole("button", { name: /confirm|delete|revoke/i })
      .last();
    if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await confirmBtn.click();
    }

    await expect(page.getByText(revokeKeyName)).toHaveCount(0, { timeout: 10000 });
    revokeKeyId = null;
  });
});
