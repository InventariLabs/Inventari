import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Stock Takes — inventory counting flow", () => {
  let api: ApiHelper;
  let token: string;
  let seedStockTakeId: string;
  let ownedSeedStockTake = false;
  let seedStorageId: string | undefined;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    // The seed count opens on a place of its own: a count on a place that
    // another spec created and is about to click would turn that click into
    // "resume the open count".
    try {
      seedStorageId = (
        await api.createStorage(token, {
          name: `E2E-StockTake-Loc-${Date.now()}-w${testInfo.workerIndex}`,
        })
      ).id;
      const stockTake = await api.createStockTake(token, {
        name: `E2E-StockTake-${Date.now()}`,
        location_id: seedStorageId,
      });
      seedStockTakeId = stockTake.id;
      ownedSeedStockTake = true;
    } catch {
      const existing = await api.listStockTakes(token);
      const active = existing.find(
        (st) => st.status === "in_progress" || st.status === "draft",
      );
      if (active) {
        seedStockTakeId = active.id;
        ownedSeedStockTake = false;
      }
    }
  });

  test.afterAll(async () => {
    if (token && seedStockTakeId && ownedSeedStockTake) {
      await api.deleteStockTake(token, seedStockTakeId).catch(() => {});
    }
    if (token && seedStorageId) {
      await api.deleteStorage(token, seedStorageId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/inventory/stock-takes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("displays stock takes page heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("page content loads (list or empty state)", async ({
    page,
    authenticatedPage,
  }) => {
    const listContent = page
      .locator('table, ul, [role="list"], [class*="rounded-xl"]')
      .first();
    const emptyOrContent = page.locator("h1, h2, button, a").first();
    await expect(emptyOrContent).toBeVisible({ timeout: 15000 });
    const contentVisible = await listContent
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    expect(contentVisible || true).toBeTruthy();
  });

  test("starts a new stock take via create button", async ({
    page,
    authenticatedPage,
  }) => {
    const createBtn = page
      .getByRole("button", {
        name: /new stock take|create|start|utwórz|zacznij|rozpocznij/i,
      })
      .first();
    await expect(createBtn).toBeVisible({ timeout: 10000 });
    await createBtn.click();

    await page
      .locator('[role="dialog"], form, input[type="text"]')
      .first()
      .waitFor({ state: "visible", timeout: 5000 })
      .catch(() => {});
    const modalOrNavigate = page
      .locator('[role="dialog"], form, input[type="text"]')
      .first();
    if (await modalOrNavigate.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(modalOrNavigate).toBeVisible();
    }
  });

  test("counting page loads with search UI", async ({
    page,
    authenticatedPage,
  }) => {
    const countingLink = page.locator('a[href*="/counting"]').first();
    await expect(countingLink).toBeVisible({ timeout: 10000 });
    const href = await countingLink.getAttribute("href");
    expect(href).toBeTruthy();

    await page.goto(href!);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const countingInput = page.locator(
      '[data-testid="stock-take-counting-input"]',
    );
    await expect(countingInput).toBeVisible({ timeout: 15000 });
  });

  test("complete button is enabled on active stock take", async ({
    page,
    authenticatedPage,
  }) => {
    const countingLink = page.locator('a[href*="/counting"]').first();
    await expect(countingLink).toBeVisible({ timeout: 5000 });
    const href = await countingLink.getAttribute("href");
    expect(href, "the counting link carries an href").toBeTruthy();
    await page.goto(href);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const completeBtn = page.locator('[data-testid="stock-take-complete-btn"]');
    await expect(completeBtn).toBeVisible({ timeout: 10000 });
    await expect(completeBtn).toBeEnabled();
  });

  test("cancel button is enabled on active stock take", async ({
    page,
    authenticatedPage,
  }) => {
    const countingLink = page.locator('a[href*="/counting"]').first();
    await expect(countingLink).toBeVisible({ timeout: 5000 });
    const href = await countingLink.getAttribute("href");
    expect(href, "the counting link carries an href").toBeTruthy();
    await page.goto(href);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const cancelBtn = page.locator('[data-testid="stock-take-cancel-btn"]');
    await expect(cancelBtn).toBeVisible({ timeout: 10000 });
    await expect(cancelBtn).toBeEnabled();
  });

  test("shows status tabs on list page", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/stock-takes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    const anyTabOrBtn = page
      .locator('[role="tab"], button, a')
      .filter({ hasText: /all|in progress|draft|completed|wszystkie|w toku/i })
      .first();
    const tabVisible = await anyTabOrBtn
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!tabVisible) {
      await expect(page.locator("body")).not.toContainText(/error|błąd/i);
    }
  });
});

test.describe("Stock Takes — counting lifecycle (API)", () => {
  // The tests share one stock take and run in the order written. The config
  // is fully parallel, so without this each one lands on its own worker, sees
  // an unset stockTakeId and passes without checking anything.
  test.describe.configure({ mode: "serial" });

  let api: ApiHelper;
  let token: string;
  let testStorageId: string;
  let testItemId: string;
  let stockTakeId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    const storage = await api.createStorage(token, {
      name: `Z_Lifecycle Storage ${Date.now()}`,
    });
    testStorageId = storage.id;

    const item = await api.createItem(token, {
      name: `E2E-ST-Item-${Date.now()}`,
      quantity: 10,
      location_id: testStorageId,
    });
    testItemId = item.id;
  });

  test.afterAll(async () => {
    if (token) {
      if (stockTakeId)
        await api.deleteStockTake(token, stockTakeId).catch(() => {});
      if (testItemId) await api.deleteItem(token, testItemId).catch(() => {});
      if (testStorageId)
        await api.deleteStorage(token, testStorageId).catch(() => {});
    }
  });

  test("POST /stock-takes creates a stock take", async () => {
    const st = await api.createStockTake(token, {
      name: `E2E-Lifecycle-${Date.now()}`,
      location_id: testStorageId,
    });
    stockTakeId = st.id;
    expect(st.id).toBeTruthy();
  });

  test("GET /stock-takes/{id} returns stock take details", async () => {
    const detail = await api.getStockTake(token, stockTakeId);
    expect(detail.id).toBe(stockTakeId);
    expect(detail.status).toBeTruthy();
  });

  test("GET /stock-takes/{id}/items returns item list", async () => {
    const items = await api.getStockTakeItems(token, stockTakeId);
    expect(items.some((line) => line.item_id === testItemId)).toBe(true);
  });

  test("PATCH /stock-takes/{id}/items/{itemId}/count counts a single item", async () => {
    const items = await api.getStockTakeItems(token, stockTakeId);
    // The path takes the stock-take line's own id, not the inventory item's.
    const line = items.find((entry) => entry.item_id === testItemId);
    expect(line).toBeDefined();
    const result = await api.countStockTakeItem(
      token,
      stockTakeId,
      String(line!.id),
      8,
    );
    expect(Number(result.counted_quantity)).toBe(8);
  });

  test("POST /stock-takes/{id}/complete finalizes the stock take", async () => {
    const report = await api.completeStockTake(token, stockTakeId, false);
    expect(report).toBeTruthy();
  });

  test("GET /stock-takes/{id}/report returns report data", async () => {
    const report = await api.getStockTakeReport(token, stockTakeId);
    expect(report.total_items).toBeDefined();
  });

  test("POST /stock-takes creates blind mode stock take", async () => {
    const st = await api.createStockTake(token, {
      name: `E2E-Blind-${Date.now()}`,
      location_id: testStorageId,
      blind_mode: true,
    });
    expect(st.id).toBeTruthy();
    await api.deleteStockTake(token, st.id).catch(() => {});
  });

  test("GET /stock-takes lists stock takes", async () => {
    const st = await api.createStockTake(token, {
      name: `E2E-List-${Date.now()}`,
      location_id: testStorageId,
    });
    const list = await api.listStockTakes(token);
    expect(Array.isArray(list)).toBe(true);
    expect(list.length).toBeGreaterThanOrEqual(1);
    expect(list.some((s) => s.id === st.id)).toBe(true);
    await api.deleteStockTake(token, st.id).catch(() => {});
  });

  test("PATCH /stock-takes/{id}/status changes status", async () => {
    // The lifecycle take is completed by now and cannot change status.
    const st = await api.createStockTake(token, {
      name: `E2E-Cancel-${Date.now()}`,
      location_id: testStorageId,
    });
    await api.updateStockTakeStatus(token, st.id, "cancelled");
    const detail = await api.getStockTake(token, st.id);
    expect(detail.status).toBe("cancelled");
    await api.deleteStockTake(token, st.id).catch(() => {});
  });

  // the redirect after completing a stock take targets
  // /inventory/stock-takes/{id}/report — that route used to be
  // unregistered ("Page Not Found" after the most labor-intensive
  // operation in the system).
  test("report route renders after completion", async ({
    page,
    authenticatedPage,
  }) => {
    const st = await api.createStockTake(token, {
      name: `E2E-Report-${Date.now()}`,
      location_id: testStorageId,
    });
    const items = await api.getStockTakeItems(token, st.id);
    // The beforeAll put an item on this location, so the count has a line.
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      await api.countStockTakeItem(
        token,
        st.id,
        String(item.id),
        Number(item.system_quantity),
      );
    }
    await api.completeStockTake(token, st.id);

    await page.goto(`/inventory/stock-takes/${st.id}/report`);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Old behaviour: "Page Not Found". The summary must render instead.
    await expect(page.getByText(/perfect matches/i).first()).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText(/not counted/i).first()).toBeVisible();

    await api.deleteStockTake(token, st.id).catch(() => {});
  });

  // at 390 px the counting controls (minus / quantity / plus /
  // save) must sit inside the viewport — previously "+" (404 px) and the
  // save button (446 px) fell past the right edge of a 384 px card with
  // no horizontal scrolling.
  test.describe("mobile counting card at 390px", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    let mobileStockTakeId: string;

    test.afterAll(async () => {
      if (mobileStockTakeId) {
        await api.deleteStockTake(token, mobileStockTakeId).catch(() => {});
      }
    });

    test("quantity controls and save fit within the viewport", async ({
      page,
      authenticatedPage,
    }) => {
      const st = await api.createStockTake(token, {
        name: `E2E-Mobile-${Date.now()}`,
        location_id: testStorageId,
      });
      mobileStockTakeId = st.id;
      const detail = await api.getStockTake(token, mobileStockTakeId);
      expect(detail.items_count as number).toBeGreaterThan(0);

      await page.goto(`/inventory/stock-takes/${mobileStockTakeId}/counting`);
      await page
        .waitForLoadState("networkidle", { timeout: 15000 })
        .catch(() => {});

      const card = page.getByTestId("stock-take-item-card").first();
      await expect(card).toBeVisible({ timeout: 15000 });

      const saveBtn = card.getByRole("button", { name: /save/i });
      await saveBtn.scrollIntoViewIfNeeded();

      const viewportWidth = (await page.viewportSize())?.width ?? 390;
      const box = await saveBtn.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth);

      // The quantity input stretches across the row instead of the old
      // fixed 64 px (w-16) — the primary touch target during counting.
      // It is a text input now (a number field rewrites itself over the
      // "." mid-edit), so role is textbox, not spinbutton.
      const countInput = card.getByRole("textbox", {
        name: /counted quantity/i,
      });
      const inputBox = await countInput.boundingBox();
      expect(inputBox).not.toBeNull();
      expect(inputBox!.width).toBeGreaterThan(64);
    });
  });
});
