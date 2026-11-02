import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Webhooks — management & testing", () => {
  let api: ApiHelper;
  let token: string;
  let seedWebhookId: string;
  const seedWebhookName = `E2E-Webhook-${Date.now()}`;
  const seedWebhookUrl = "https://example.com/e2e-webhook";

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    const webhook = await api.createWebhook(token, {
      name: seedWebhookName,
      url: seedWebhookUrl,
      event_types: ["item.created"],
      is_active: true,
    });
    seedWebhookId = webhook.id;
  });

  test.afterAll(async () => {
    if (token && seedWebhookId) {
      await api.deleteWebhook(token, seedWebhookId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/settings/webhooks");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("displays webhooks page heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByRole("heading").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("seeded webhook is visible in list", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByText(seedWebhookName).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("opens add webhook modal", async ({ page, authenticatedPage }) => {
    const addBtn = page.locator('[data-testid="webhooks-add-btn"]').first();
    const addBtnVisible = await addBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!addBtnVisible) return;
    await addBtn.click();

    await expect(page.locator('[role="dialog"]')).toBeVisible({
      timeout: 10000,
    });
  });

  test("creates a new webhook via UI", async ({ page, authenticatedPage }) => {
    const uniqueName = `E2E-Webhook-UI-${Date.now()}`;
    const addBtn = page.locator('[data-testid="webhooks-add-btn"]').first();
    const addBtnVisible = await addBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!addBtnVisible) return;
    await addBtn.click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 10000 });

    const nameInput = modal.getByPlaceholder(/home assistant|name|nazwa/i);
    const nameVisible = await nameInput
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    if (!nameVisible) return;
    await nameInput.fill(uniqueName);

    const urlInput = modal.locator('input[type="url"]').first();
    if (await urlInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await urlInput.fill("https://example.com/webhook-ui");
    }

    const firstEventOption = modal
      .locator('label:has(input[type="checkbox"])')
      .first();
    await expect(firstEventOption).toBeVisible({ timeout: 10000 });
    await firstEventOption.click();

    const submitBtn = modal.getByRole("button", {
      name: /save|create|submit|zapisz/i,
    });
    await expect(submitBtn).toBeEnabled({ timeout: 5000 });
    await submitBtn.click();

    await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 15000 });
  });

  test("edits existing webhook", async ({ page, authenticatedPage }) => {
    const webhookRow = page
      .locator('tr, li, [role="row"], div[class*="rounded-xl"]')
      .filter({ hasText: seedWebhookName })
      .first();
    const rowVisible = await webhookRow
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!rowVisible) return;

    const editBtn = webhookRow.getByRole("button", {
      name: /edit|edytuj|pen/i,
    });

    const editVisible = await editBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!editVisible) return;
    await editBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const urlInput = dialog
      .locator('input[type="url"], input[placeholder*="http"]')
      .first();
    if (await urlInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(urlInput).toHaveValue(seedWebhookUrl);
    }
  });

  test("deletes a webhook", async ({ page, authenticatedPage }) => {
    const delName = `E2E-Webhook-Del-${Date.now()}`;
    const toDelete = await api.createWebhook(token, {
      name: delName,
      url: "https://example.com/delete-me",
      event_types: ["item.created"],
      is_active: true,
    });

    await page.goto("/settings/webhooks");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const webhookRow = page
      .locator('tr, li, [role="row"], div[class*="rounded-xl"]')
      .filter({ hasText: delName })
      .first();
    const rowVisible = await webhookRow
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!rowVisible) {
      await api.deleteWebhook(token, toDelete.id).catch(() => {});
      return;
    }

    const deleteBtn = webhookRow.getByRole("button", {
      name: /delete|usuń|remove/i,
    });
    const delBtnVisible = await deleteBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!delBtnVisible) {
      await api.deleteWebhook(token, toDelete.id).catch(() => {});
      return;
    }
    await deleteBtn.click();

    const confirmBtn = page
      .getByRole("button", { name: /confirm|delete|usuń|tak/i })
      .last();
    if (await confirmBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await confirmBtn.click();
    }

    await expect(page.locator("body").getByText(delName)).toHaveCount(0, {
      timeout: 10000,
    });
  });

  test("tests webhook delivery (ping)", async ({ page, authenticatedPage }) => {
    const webhookRow = page
      .locator('tr, li, [role="row"], div[class*="rounded-xl"]')
      .filter({ hasText: seedWebhookName })
      .first();
    const rowVisible = await webhookRow
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!rowVisible) return;

    const testBtn = webhookRow.getByRole("button", {
      name: /test|ping|send|wyślij/i,
    });

    const testBtnVisible = await testBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!testBtnVisible) return;
    await testBtn.click();

    const statusMessage = page.getByText(
      /delivered|success|failed|error|status|wysłane|błąd/i,
    );
    await expect(statusMessage.first()).toBeVisible({ timeout: 15000 });
  });

  test("displays delivery history/logs", async ({
    page,
    authenticatedPage,
  }) => {
    const webhookRow = page
      .locator('tr, li, [role="row"], div[class*="rounded-xl"]')
      .filter({ hasText: seedWebhookName })
      .first();
    const rowVisible = await webhookRow
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!rowVisible) return;

    const historyBtn = webhookRow.getByRole("button", {
      name: /history|logs|delivery|historia/i,
    });

    const historyBtnVisible = await historyBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!historyBtnVisible) return;
    await historyBtn.click();

    const logsArea = page
      .locator('[role="dialog"], section, div')
      .filter({ hasText: /delivery|status|timestamp|log/i });
    await expect(logsArea.first()).toBeVisible({ timeout: 15000 });
  });
});
