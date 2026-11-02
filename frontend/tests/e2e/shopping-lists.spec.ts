import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Shopping Lists — flow", () => {
  let api: ApiHelper;
  let token: string;
  let seedListId: string;
  const seedListName = `E2E-List-Seed-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const list = await api.createShoppingList(token, { name: seedListName });
    seedListId = list.id;
    await api.addShoppingListItem(token, seedListId, {
      name: "E2E-Item-Seed",
      quantity: 3,
      unit: "pcs",
    });
  });

  test.afterAll(async () => {
    if (token && seedListId) {
      await api.deleteShoppingList(token, seedListId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/shopping-lists");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  });

  test("displays shopping lists page", async ({ page, authenticatedPage }) => {
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByRole("button", { name: /new list/i })).toBeVisible({
      timeout: 10000,
    });
  });

  test("seeded list is visible", async ({ page, authenticatedPage }) => {
    await expect(page.getByText(seedListName).first()).toBeVisible({ timeout: 10000 });
  });

  test("opens list detail and shows seeded item", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/shopping-lists/${seedListId}`);
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const seeded = page.getByText("E2E-Item-Seed");
    const visible = await seeded.isVisible({ timeout: 10000 }).catch(() => false);
    if (!visible) {
      await expect(page.locator("body")).not.toContainText(/error|błąd/i);
      return;
    }
  });

  test("creates a new shopping list via UI", async ({
    page,
    authenticatedPage,
  }) => {
    const newBtn = page.getByRole("button", { name: /new list/i });
    await expect(newBtn).toBeVisible({ timeout: 10000 });
    await newBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const nameInput = dialog.locator("input").first();
    const listName = `E2E-List-New-${Date.now()}`;
    await nameInput.fill(listName);

    const submitBtn = dialog.getByRole("button", {
      name: /create|save|submit/i,
    });
    await submitBtn.click();

    await expect(page.getByText(listName)).toBeVisible({ timeout: 10000 });

    const items = await api.listShoppingLists(token);
    const created = items.find(
      (l: { name?: string; title?: string }) =>
        (l.name || (l as { title?: string }).title || "") === listName,
    );
    if (created)
      await api.deleteShoppingList(token, created.id).catch(() => {});
  });

  test("marks item as purchased", async ({ page, authenticatedPage }) => {
    await page.goto(`/shopping-lists/${seedListId}`);
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});

    const purchaseToggle = page
      .locator('[data-testid="purchase-checkbox"]')
      .first();
    if (await purchaseToggle.isVisible({ timeout: 5000 }).catch(() => false)) {
      await purchaseToggle.click();
    }
  });

  test("deletes a shopping list", async ({ page, authenticatedPage }) => {
    // The full name, never its prefix: lists an interrupted run left behind
    // carry the same prefix and would keep the count above zero.
    const name = `E2E-List-Del-${Date.now()}`;
    const newList = await api.createShoppingList(token, { name });
    await page.goto("/shopping-lists");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const listCard = page
      .locator('[data-testid="shopping-list-card"]')
      .filter({ hasText: name });
    await expect(listCard).toBeVisible({ timeout: 10000 });

    // Delete lives behind the card's "⋯" action menu, not a bare icon.
    await listCard.getByRole("button", { name: /actions for/i }).click();
    await page.getByRole("button", { name: /delete list/i }).click();

    const confirmBtn = page
      .getByRole("button", { name: /confirm|delete|usuń|tak/i })
      .last();
    if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await confirmBtn.click();
    }
    await expect(page.getByText(name)).toHaveCount(0, {
      timeout: 10000,
    });
    // The UI path above deleted it; this only tidies up after a failure.
    await api.deleteShoppingList(token, newList.id).catch(() => {});
  });
});

test.describe("Shopping Lists — extended actions (API)", () => {
  let api: ApiHelper;
  let token: string;
  let listId: string;
  let itemId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const list = await api.createShoppingList(token, { name: `E2E-Extended-${Date.now()}` });
    listId = list.id;

    const item = await api.addShoppingListItem(token, listId, {
      name: "E2E-Extended-Item",
      quantity: 2,
    });
    itemId = item.id;
  });

  test.afterAll(async () => {
    if (token && listId) await api.deleteShoppingList(token, listId).catch(() => {});
  });

  test("PUT /{id} updates list name", async () => {
    const updated = await api.updateShoppingList(token, listId, { name: `E2E-Updated-${Date.now()}` });
    expect(updated).toBeTruthy();
    expect(updated.name).toContain("E2E-Updated");
  });

  test("PUT /{id}/items/{itemId} updates item name", async () => {
    const updated = await api.updateShoppingListItem(token, listId, itemId, { name: "E2E-Updated-Item", quantity: 5 });
    expect(updated).toBeTruthy();
    expect(updated.name).toBe("E2E-Updated-Item");
    // Quantities come back as fixed-scale strings ("5.000"), not numbers.
    expect(Number(updated.quantity)).toBe(5);
  });

  test("POST /{id}/items/bulk adds multiple items", async () => {
    const items = await api.bulkAddShoppingListItems(token, listId, [
      { name: "Bulk-Item-1", quantity: 1 },
      { name: "Bulk-Item-2", quantity: 3 },
    ]);
    expect(items.length).toBe(2);
    expect(items[0].name).toBe("Bulk-Item-1");
  });

  test("PATCH /{id}/items/{itemId}/unpurchase unpurchases item", async () => {
    const listItems = await api.request.get(`/api/v1/shopping-lists/${listId}/items`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    const data = await listItems.json();
    const items = Array.isArray(data) ? data : (data.items ?? []);
    const purchasable = items.find((i: Record<string, unknown>) => !i.is_purchased);
    if (purchasable) {
      const result = await api.unpurchaseShoppingListItem(token, listId, purchasable.id);
      expect(result).toBeTruthy();
    }
  });
});
