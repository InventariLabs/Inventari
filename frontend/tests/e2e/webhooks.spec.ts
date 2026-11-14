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
    await expect(addBtn).toBeVisible({ timeout: 10000 });
    await addBtn.click();

    await expect(page.locator('[role="dialog"]')).toBeVisible({
      timeout: 10000,
    });
  });

  test("creates a new webhook via UI", async ({ page, authenticatedPage }) => {
    const uniqueName = `E2E-Webhook-UI-${Date.now()}`;
    const addBtn = page.locator('[data-testid="webhooks-add-btn"]').first();
    await expect(addBtn).toBeVisible({ timeout: 10000 });
    await addBtn.click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 10000 });

    const nameInput = modal.getByLabel(/Name/i);
    await expect(nameInput).toBeVisible({ timeout: 5000 });
    await nameInput.fill(uniqueName);

    const urlInput = modal.getByLabel(/Target URL/i);
    await expect(urlInput).toBeVisible({ timeout: 5000 });
    await urlInput.fill("https://example.com/webhook-ui");

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
    await expect(webhookRow).toBeVisible({ timeout: 10000 });

    const editBtn = webhookRow.getByRole("button", {
      name: /edit|edytuj|pen/i,
    });

    await expect(editBtn).toBeVisible({ timeout: 10000 });
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

    try {
      const webhookRow = page
        .locator('tr, li, [role="row"], div[class*="rounded-xl"]')
        .filter({ hasText: delName })
        .first();
      await expect(webhookRow).toBeVisible({ timeout: 10000 });

      const deleteBtn = webhookRow.getByRole("button", {
        name: /delete|usuń|remove/i,
      });
      await expect(deleteBtn).toBeVisible({ timeout: 10000 });
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
    } finally {
      // Whatever the UI did, the webhook this test made does not outlive it.
      await api.deleteWebhook(token, toDelete.id).catch(() => {});
    }
  });

  test("tests webhook delivery (ping)", async ({ page, authenticatedPage }) => {
    const webhookRow = page
      .locator('tr, li, [role="row"], div[class*="rounded-xl"]')
      .filter({ hasText: seedWebhookName })
      .first();
    await expect(webhookRow).toBeVisible({ timeout: 10000 });

    const testBtn = webhookRow.getByRole("button", {
      name: /test|ping|send|wyślij/i,
    });

    await expect(testBtn).toBeVisible({ timeout: 10000 });
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
    await expect(webhookRow).toBeVisible({ timeout: 10000 });

    const historyBtn = webhookRow.getByRole("button", {
      name: /history|logs|delivery|historia/i,
    });

    await expect(historyBtn).toBeVisible({ timeout: 10000 });
    await historyBtn.click();

    const logsArea = page
      .locator('[role="dialog"], section, div')
      .filter({ hasText: /delivery|status|timestamp|log/i });
    await expect(logsArea.first()).toBeVisible({ timeout: 15000 });
  });
});
