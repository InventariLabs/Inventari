import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Labels — pool & scanning flow", () => {
  let api: ApiHelper;
  let token: string;
  let seedLabelId: string;
  let seedShortCode: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const labels = await api.generateLabels(token, 1, "E2E");
    seedLabelId = labels[0].id;
    seedShortCode = labels[0].short_code;
  });

  test.afterAll(async () => {
    if (token && seedLabelId) {
      await api.deleteLabel(token, seedLabelId).catch(() => {});
    }
  });

  test("labels pool page loads", async ({ page, authenticatedPage }) => {
    const loaded = expectApiOk(page, "/api/v1/labels/pool");
    await page.goto("/inventory/labels");
    await loaded;

    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15000 });
  });

  test("seeded label is visible in the pool", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/labels");
    await page.waitForLoadState("networkidle").catch(() => {});

    const allTab = page
      .locator('[role="tab"]')
      .filter({ hasText: /all|wszystkie/i })
      .first();
    if (await allTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await allTab.click();
      await page.waitForLoadState("networkidle").catch(() => {});
    }

    await expect(page.getByText(seedShortCode)).toBeVisible({ timeout: 15000 });
  });

  test("generates new label(s) via UI button", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/labels");
    await page.waitForLoadState("networkidle").catch(() => {});

    const generateBtn = page
      .getByRole("button", { name: /generate|utwórz/i })
      .first();
    await expect(generateBtn).toBeVisible({ timeout: 10000 });
    await generateBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const input = dialog.locator('input[type="number"]').first();
    if (await input.isVisible({ timeout: 3000 }).catch(() => false)) {
      await input.clear();
      await input.fill("1");
    }

    const submitBtn = dialog
      .locator("button")
      .filter({ hasText: /generate|utwórz/i })
      .last();
    await submitBtn.click();

    await expect(
      page
        .locator("table, [data-testid='label-card'], [data-testid='label-row']")
        .first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("scan label page loads for seeded code", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/labels/scan/${seedShortCode}`);
    await page.waitForLoadState("networkidle").catch(() => {});

    const labelInfo = page
      .locator("body")
      .getByText(new RegExp(seedShortCode, "i"))
      .or(page.getByText(/assign|przypisz|unassign|not assigned|free/i));
    await expect(labelInfo.first()).toBeVisible({ timeout: 15000 });
  });

  test("deletes a label from the pool", async ({ page, authenticatedPage }) => {
    const toDelete = await api.generateLabels(token, 1, "DEL");
    const delCode = toDelete[0].short_code;

    await page.goto("/inventory/labels");
    await page.waitForLoadState("networkidle").catch(() => {});

    const allTab = page
      .locator('[role="tab"]')
      .filter({ hasText: /all|wszystkie/i })
      .first();
    if (await allTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await allTab.click();
      await page.waitForLoadState("networkidle").catch(() => {});
    }

    await expect(page.getByText(delCode)).toBeVisible({ timeout: 15000 });

    const labelRow = page
      .locator('[data-testid="label-card"], [data-testid="label-row"]')
      .filter({ hasText: delCode })
      .first();
    await expect(labelRow).toBeVisible({ timeout: 10000 });
    const deleteBtn = labelRow
      .locator('[data-testid="label-delete-btn"]')
      .first();
    await expect(deleteBtn).toBeVisible({ timeout: 5000 });
    await deleteBtn.click();

    const confirmBtn = page
      .getByRole("button", { name: /confirm|delete|usuń|tak/i })
      .last();
    if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await confirmBtn.click();
    }
    await expect(page.locator("body").getByText(delCode)).toHaveCount(0, {
      timeout: 10000,
    });
  });
});

test.describe("Labels — extended actions (API)", () => {
  let api: ApiHelper;
  let token: string;
  let labelId: string;
  let shortCode: string;
  let itemId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const labels = await api.generateLabels(token, 1, "EXT");
    labelId = labels[0].id;
    shortCode = labels[0].short_code;

    const storage = await api.createStorage(token, {
      name: `Z_Label_Test_${Date.now()}`,
    });
    const item = await api.createItem(token, {
      name: `E2E-Label-Item-${Date.now()}`,
      quantity: 10,
      location_id: storage.id,
    });
    itemId = item.id;
  });

  test.afterAll(async () => {
    if (token && itemId) await api.deleteItem(token, itemId).catch(() => {});
    if (token && labelId) await api.deleteLabel(token, labelId).catch(() => {});
  });

  test("GET /pool/stats returns pool statistics", async () => {
    const stats = await api.getLabelPoolStats(token);
    expect(stats).toBeTruthy();
    expect(typeof stats.total).toBe("number");
  });

  test("POST /pool/{code}/assign-item assigns label to item", async () => {
    const result = await api.assignLabelToItem(token, shortCode, itemId);
    expect(result).toBeTruthy();
    expect(result.is_assigned).toBe(true);
    expect(result.item_id).toBe(itemId);
  });

  test("POST /pool/{code}/unassign removes label from item", async () => {
    const result = await api.unassignLabel(token, shortCode);
    expect(result).toBeTruthy();
    expect(result.message).toBeTruthy();
  });
});
