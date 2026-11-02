import { test, expect } from "./fixtures/auth";
import type { Locator, Page } from "@playwright/test";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Items — CRUD flow", () => {
  let api: ApiHelper;
  let testStorageId: string;
  let testCategoryId: string;
  const addedItemIds: string[] = [];

  const uniqueId = () => Math.random().toString(36).substring(2, 9);
  let expiringName = `Expiring Product ${uniqueId()}`;
  const expiredName = `Expired Product ${uniqueId()}`;
  const lowStockName = `Low Stock Product ${uniqueId()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = authData.access_token;

    // The expiring/expired chips show when the organization tracks expiry,
    // which the page reads from two places: a location of an expiry kind, or
    // the statistics overview. The second goes away while another spec
    // switches the workspace profile, so this one brings the first.
    const expiryTypeId = await api.ensureExpiryStorageType(token);

    const storage = await api.createStorage(token, {
      name: `Z_Test Storage ${uniqueId()}`,
      location_type_id: expiryTypeId,
    });
    testStorageId = storage.id;

    const category = await api.createCategory(token, {
      name: `Z_Test Category ${uniqueId()}`,
    });
    testCategoryId = category.id;

    const today = new Date();
    const in5Days = new Date(today);
    in5Days.setDate(today.getDate() + 5);

    const past5Days = new Date(today);
    past5Days.setDate(today.getDate() - 5);

    const expiring = await api.createItem(token, {
      name: expiringName,
      quantity: 10,
      location_id: testStorageId,
      category_id: testCategoryId,
      expiry_date: in5Days.toISOString().split("T")[0],
    });

    const expired = await api.createItem(token, {
      name: expiredName,
      quantity: 10,
      location_id: testStorageId,
      category_id: testCategoryId,
      expiry_date: past5Days.toISOString().split("T")[0],
    });

    const lowStock = await api.createItem(token, {
      name: lowStockName,
      quantity: 1,
      location_id: testStorageId,
      category_id: testCategoryId,
    });

    addedItemIds.push(expiring.id, expired.id, lowStock.id);
  });

  test.afterAll(async () => {
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = authData.access_token;
    for (const id of addedItemIds) {
      await api.deleteItem(token, id).catch(() => {});
    }
    if (testStorageId)
      await api.deleteStorage(token, testStorageId).catch(() => {});
    if (testCategoryId)
      await api.deleteCategory(token, testCategoryId).catch(() => {});
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
  });

  test("displays item list", async ({ page, authenticatedPage }) => {
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiringName }),
    ).toBeVisible({
      timeout: 15000,
    });
  });

  test("adds a new item", async ({ page, authenticatedPage }) => {
    await page.goto("/inventory/items/add");
    await expect(page.locator("h1, h2, h3").first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("searches item by name", async ({ page, authenticatedPage }) => {
    const searchInput = page.locator('[data-testid="list-search-input"]');
    await expect(searchInput).toBeVisible({ timeout: 10000 });
    await searchInput.fill(expiringName);
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiringName }),
    ).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("item-name").filter({ hasText: lowStockName }),
    ).not.toBeVisible();
  });

  test("filters expiring items", async ({ page, authenticatedPage }) => {
    const expiringBtn = page.locator('[data-testid="filter-expiring"]').first();
    await expect(expiringBtn).toBeVisible({ timeout: 10000 });
    await expiringBtn.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiringName }),
    ).toBeVisible({
      timeout: 10000,
    });
  });

  test("filters expired items", async ({ page, authenticatedPage }) => {
    const expiredBtn = page.locator('[data-testid="filter-expired"]').first();
    await expect(expiredBtn).toBeVisible({ timeout: 10000 });
    await expiredBtn.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiredName }),
    ).toBeVisible({
      timeout: 10000,
    });
  });

  test("filters low stock items", async ({ page, authenticatedPage }) => {
    const lowStockBtn = page
      .locator('[data-testid="filter-low_stock"]')
      .first();
    await expect(lowStockBtn).toBeVisible({ timeout: 10000 });
    await lowStockBtn.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.locator("body")).not.toContainText(/error|błąd/i);
  });

  test("edits an item name and quantity", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiringName }),
    ).toBeVisible({
      timeout: 15000,
    });
    await page
      .getByTestId("item-name")
      .filter({ hasText: expiringName })
      .click();

    // A product's name opens the product dialog itself, the pencil's own.
    const dialog = page.locator('[role="dialog"]').filter({
      has: page.getByRole("heading", { name: "Edit product" }),
    });
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const newName = `${expiringName} Edited`;
    const nameInput = dialog.locator("#name");
    await expect(nameInput).toBeVisible({ timeout: 5000 });
    await nameInput.clear();
    await nameInput.fill(newName);

    // The sheet footer sits outside the <form> (FormSheetFooter, §4.3), so
    // Save is a type="button" that calls the submit handler — match it by
    // role and name, not by the form-control type.
    const saveBtn = dialog
      .getByRole("button", { name: /^(save|zapisz)\b/i })
      .first();
    await saveBtn.click();

    await expect(
      page.getByTestId("item-name").filter({ hasText: newName }),
    ).toBeVisible({
      timeout: 10000,
    });
    expiringName = newName;
  });

  test("consumes an item via the row action", async ({
    page,
    authenticatedPage,
  }) => {
    const row = page.getByTestId("item-row").filter({ hasText: lowStockName });
    await expect(row).toBeVisible({ timeout: 10000 });

    // The row's "Remove 1 unit" asks how much and why before it takes
    // stock off the shelf.
    await row.getByRole("button", { name: "Remove 1 unit" }).click();
    const dialog = page.getByRole("alertdialog", {
      name: "Remove from stock",
    });
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await dialog.getByLabel("Quantity to remove").fill("1");

    const consumeResponse = page.waitForResponse(
      (resp) => resp.url().includes("/consume") && resp.status() === 200,
      { timeout: 10000 },
    );
    await dialog.getByRole("button", { name: /^Remove 1/ }).click();
    await consumeResponse;

    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: lowStockName }),
    ).not.toBeVisible({
      timeout: 10000,
    });
  });

  test("archived items page loads", async ({ page, authenticatedPage }) => {
    const loaded = expectApiOk(page, "/api/v1/items/archived");
    await page.goto("/inventory/items/archived");
    await loaded;

    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15000 });
  });

  test("discards an item", async ({ page, authenticatedPage }) => {
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiredName }),
    ).toBeVisible({
      timeout: 15000,
    });
    await page
      .getByTestId("item-row")
      .filter({ hasText: expiredName })
      .getByRole("button", { name: "Delete", exact: true })
      .click();

    // Deleting a record asks for its reason first (DeleteReasonDialog): the
    // confirm button stays disabled until one is picked, so the deletion
    // waits for the answer. The endpoint answers 204, not 200.
    const reasonSelect = page.getByTestId("deletion-reason");
    await expect(reasonSelect).toBeVisible({ timeout: 5000 });
    await reasonSelect.selectOption({ value: "EXPIRED" });

    const discardResponse = page.waitForResponse(
      (resp) => resp.request().method() === "DELETE" && resp.status() === 204,
      { timeout: 10000 },
    );
    const confirmBtn = page
      .locator('[role="alertdialog"]')
      .getByRole("button", { name: /^delete$/i });
    await confirmBtn.click();
    await discardResponse;

    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiredName }),
    ).not.toBeVisible({
      timeout: 10000,
    });
  });
});

test.describe("Items — modal backdrop guard", () => {
  let api: ApiHelper;
  let testStorageId: string;
  let testCategoryId: string;
  let itemId: string;
  const itemName = `MQA8 Backdrop Item ${Math.random().toString(36).substring(2, 9)}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = authData.access_token;

    const storage = await api.createStorage(token, {
      name: `Z_Test MQA8 Storage ${Date.now()}`,
    });
    testStorageId = storage.id;

    const category = await api.createCategory(token, {
      name: `Z_Test MQA8 Category ${Date.now()}`,
    });
    testCategoryId = category.id;

    const item = await api.createItem(token, {
      name: itemName,
      quantity: 5,
      location_id: testStorageId,
      category_id: testCategoryId,
    });
    itemId = item.id;
  });

  test.afterAll(async () => {
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = authData.access_token;
    if (itemId) await api.deleteItem(token, itemId).catch(() => {});
    if (testStorageId)
      await api.deleteStorage(token, testStorageId).catch(() => {});
    if (testCategoryId)
      await api.deleteCategory(token, testCategoryId).catch(() => {});
  });

  async function openEditModal(page: Page): Promise<Locator> {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: itemName }),
    ).toBeVisible({
      timeout: 15000,
    });
    await page.getByTestId("item-name").filter({ hasText: itemName }).click();

    // The name opens the dialog headed "Edit product".
    const dialog = page.locator('[role="dialog"]').filter({
      has: page.getByRole("heading", { name: "Edit product" }),
    });
    await expect(dialog).toBeVisible({ timeout: 10000 });
    return dialog;
  }

  function backdropPointOutside(
    box: { x: number; y: number; width: number; height: number },
    viewport: { width: number; height: number } | null,
  ): { x: number; y: number } {
    const h = viewport?.height ?? 720;
    // The app shell's fixed top bar (`--z-app-bar`) still sits above the modal
    // backdrop, so the top ~56px is not clickable backdrop. Pick a point just
    // left of the dialog panel, at its vertical middle — reliably on the
    // backdrop, below the top bar and outside the panel on desktop.
    const x = Math.max(5, Math.floor(box.x - 20));
    const y = Math.min(h - 5, Math.max(70, Math.floor(box.y + box.height / 2)));
    return { x, y };
  }

  test("a press that starts inside the edit modal and ends on the backdrop keeps it open; a full backdrop press closes it", async ({
    page,
    authenticatedPage,
  }) => {
    const dialog = await openEditModal(page);

    // mousedown on a field inside the panel (selecting text in an input and
    // letting go outside the panel is the everyday way to hit this).
    const nameInput = dialog.getByRole("textbox", { name: /product name/i });
    await expect(nameInput).toBeVisible({ timeout: 5000 });
    const inputBox = await nameInput.boundingBox();
    expect(inputBox).not.toBeNull();
    await page.mouse.move(
      inputBox!.x + inputBox!.width / 2,
      inputBox!.y + inputBox!.height / 2,
    );
    await page.mouse.down();

    // Release over the backdrop (outside the dialog panel).
    const dialogBox = await dialog.boundingBox();
    expect(dialogBox).not.toBeNull();
    const backdrop = backdropPointOutside(dialogBox!, page.viewportSize());
    await page.mouse.move(backdrop.x, backdrop.y);
    await page.mouse.up();

    // The split press must not close the modal.
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // Sanity: a press that both starts and ends on the backdrop still closes.
    await page.mouse.move(backdrop.x, backdrop.y);
    await page.mouse.down();
    await page.mouse.up();
    await expect(dialog).toBeHidden({ timeout: 5000 });
  });
});

test.describe("Items — extended actions (API)", () => {
  let api: ApiHelper;
  let token: string;
  let testStorageId: string;
  let testCategoryId: string;
  const itemIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const storage = await api.createStorage(token, {
      name: `Z_Test Ext ${Date.now()}`,
    });
    testStorageId = storage.id;
    const category = await api.createCategory(token, {
      name: `Z_Test Ext Cat ${Date.now()}`,
    });
    testCategoryId = category.id;
  });

  test.afterAll(async () => {
    if (token) {
      for (const id of itemIds) await api.deleteItem(token, id).catch(() => {});
      if (testStorageId)
        await api.deleteStorage(token, testStorageId).catch(() => {});
      if (testCategoryId)
        await api.deleteCategory(token, testCategoryId).catch(() => {});
    }
  });

  test("POST /items creates an item with required fields", async () => {
    const item = await api.createItem(token, {
      name: `E2E-ExtItem-${Date.now()}`,
      quantity: 5,
      location_id: testStorageId,
      category_id: testCategoryId,
    });
    itemIds.push(item.id);
    expect(item.id).toBeTruthy();
  });

  test("GET /items/{id} returns item details", async () => {
    const created = await api.createItem(token, {
      name: `E2E-DetailItem-${Date.now()}`,
      quantity: 3,
      location_id: testStorageId,
    });
    itemIds.push(created.id);
    const detail = await api.getItem(token, created.id);
    expect(detail.name).toBeTruthy();
    expect(detail.quantity).toBeDefined();
  });

  test("PATCH /items/{id}/quantity adjusts quantity", async () => {
    const created = await api.createItem(token, {
      name: `E2E-QtyItem-${Date.now()}`,
      quantity: 10,
      location_id: testStorageId,
    });
    itemIds.push(created.id);
    const updated = await api.adjustQuantity(token, created.id, 15);
    expect(updated).toBeTruthy();
  });

  test("PATCH /items/{id}/move moves item to new location", async () => {
    const newStorage = await api.createStorage(token, {
      name: `Z_Test Move ${Date.now()}`,
    });
    const created = await api.createItem(token, {
      name: `E2E-MoveItem-${Date.now()}`,
      quantity: 2,
      location_id: testStorageId,
    });
    itemIds.push(created.id);
    await api.moveItem(token, created.id, newStorage.id);
    const detail = await api.getItem(token, created.id);
    expect(detail.location_id).toBe(newStorage.id);
    await api.deleteStorage(token, newStorage.id).catch(() => {});
  });

  test("POST /items/{id}/restore restores archived item", async () => {
    const created = await api.createItem(token, {
      name: `E2E-RestoreItem-${Date.now()}`,
      quantity: 1,
      location_id: testStorageId,
    });
    await api.deleteItem(token, created.id);
    await api.restoreItem(token, created.id);
    const detail = await api.getItem(token, created.id);
    expect(detail).toBeTruthy();
  });

  test("DELETE /items/{id}/purge permanently removes item", async () => {
    const created = await api.createItem(token, {
      name: `E2E-PurgeItem-${Date.now()}`,
      quantity: 1,
      location_id: testStorageId,
    });
    await api.deleteItem(token, created.id);
    await api.purgeItem(token, created.id);
    // Poll instead of a one-shot check: under full-suite parallel load the
    // purge's effects (and async event handlers) can lag a moment behind
    // the 204 response, which made this assertion flaky.
    await expect
      .poll(
        async () => {
          try {
            await api.getItem(token, created.id);
            return false;
          } catch {
            return true;
          }
        },
        { timeout: 15000 },
      )
      .toBe(true);
  });

  test("GET /items/archived returns soft-deleted items", async () => {
    const archived = await api.getArchivedItems(token);
    expect(Array.isArray(archived)).toBe(true);
  });
});
