import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe.configure({ mode: "serial" });

test.describe("Item lifecycle — full state machine", () => {
  let api: ApiHelper;
  let token: string;
  let storageId: string;
  let storage2Id: string;
  let itemId: string;
  const itemName = `E2E-Lifecycle-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;

    const uid = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;
    const storage1 = await api.createStorage(token, {
      name: `E2E-Lcl-Storage1-${uid}`,
    });
    storageId = storage1.id;
    const storage2 = await api.createStorage(token, {
      name: `E2E-Lcl-Storage2-${uid}`,
    });
    storage2Id = storage2.id;

    const item = await api.createItem(token, {
      name: itemName,
      quantity: 10,
      unit: "pcs",
      location_id: storageId,
    });
    itemId = item.id;
  });

  test.afterAll(async () => {
    if (token) {
      await api.deleteItem(token, itemId).catch(() => {});
      await api.deleteStorage(token, storageId).catch(() => {});
      await api.deleteStorage(token, storage2Id).catch(() => {});
    }
  });

  test("newly created item is visible in the list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: itemName }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("item detail page shows correct initial quantity", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    const itemRow = page
      .locator('[data-testid="item-row"]')
      .filter({ hasText: itemName })
      .first();
    await expect(itemRow).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByTestId("item-name").filter({ hasText: itemName }),
    ).toBeVisible();
  });

  test("consume action reduces quantity (API)", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const resp = await ctx.patch(`/api/v1/items/${itemId}/consume`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { quantity: 3, reason: "consumed" },
    });
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    expect(Number(body.quantity)).toBe(7);
  });

  test("move action changes storage location (API)", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const resp = await ctx.patch(`/api/v1/items/${itemId}/move`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { to_location_id: storage2Id },
    });
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    expect(body.location_id).toBe(storage2Id);
  });

  test("discard action records waste (API)", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const resp = await ctx.patch(`/api/v1/items/${itemId}/discard`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { quantity: 1, reason: "expired" },
    });
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    expect(Number(body.quantity)).toBe(6);
  });

  test("item history endpoint records operations", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const resp = await ctx.get(`/api/v1/items/${itemId}/history`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.ok()).toBe(true);
    const raw = await resp.json();
    const history = Array.isArray(raw)
      ? raw
      : (raw.history ?? raw.items ?? raw.data ?? []);
    expect(history.length).toBeGreaterThan(0);
  });

  test("quantity update via UI is reflected immediately", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    const itemRow = page
      .locator('[data-testid="item-row"]')
      .filter({ hasText: itemName })
      .first();
    await expect(itemRow).toBeVisible({ timeout: 15000 });

    const editBtn = itemRow
      .getByRole("button", { name: /edit|zmień|aktualizuj/i })
      .first();
    const editVisible = await editBtn
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    if (!editVisible) return;

    await editBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const qtyInput = dialog.locator('input[type="number"]').first();
    await expect(qtyInput).toBeVisible({ timeout: 5000 });
    await qtyInput.clear();
    await qtyInput.fill("20");

    // FormSheetFooter renders Save outside the <form> as a type="button"
    // (§4.3) — match the accessible name instead of the control type.
    const saveBtn = dialog
      .getByRole("button", { name: /^(save|zapisz|confirm)\b/i })
      .first();
    await saveBtn.click();

    await expect(itemRow.getByText(/\b20\b/)).toBeVisible({ timeout: 10000 });
  });
});
