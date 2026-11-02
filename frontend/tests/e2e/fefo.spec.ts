import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("FEFO — First Expired, First Out", () => {
  let api: ApiHelper;
  let token: string;
  let itemExpiringId: string;
  let itemFreshId: string;
  let storageId: string;

  const today = new Date();
  const tomorrow = new Date(today);
  const inThirtyDays = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  inThirtyDays.setDate(today.getDate() + 30);

  const formatDate = (d: Date) => d.toISOString().split("T")[0];

  const uid = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;
  const expiringName = `E2E-Yoghurt-Expiring-${uid}`;
  const freshName = `E2E-Yoghurt-Fresh-${uid}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;

    const storage = await api.createStorage(token, {
      name: `E2E-FEFO-Storage-${Date.now()}-${Math.floor(Math.random() * 100000)}`,
    });
    storageId = storage.id;

    const expiring = await api.createItem(token, {
      name: expiringName,
      quantity: 2,
      unit: "pcs",
      expiry_date: formatDate(tomorrow),
      location_id: storageId,
    });
    itemExpiringId = expiring.id;

    const fresh = await api.createItem(token, {
      name: freshName,
      quantity: 2,
      unit: "pcs",
      expiry_date: formatDate(inThirtyDays),
      location_id: storageId,
    });
    itemFreshId = fresh.id;
  });

  test.afterAll(async () => {
    if (token) {
      await api.deleteItem(token, itemExpiringId).catch(() => {});
      await api.deleteItem(token, itemFreshId).catch(() => {});
      await api.deleteStorage(token, storageId).catch(() => {});
    }
  });

  test("expiring item is visible in items list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: expiringName }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("fresh item is visible in items list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: freshName }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("both items are visible in items list (order depends on sort)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const expiringEl = page
      .getByTestId("item-name")
      .filter({ hasText: expiringName });
    const freshEl = page
      .getByTestId("item-name")
      .filter({ hasText: freshName });
    await expect(expiringEl).toBeVisible({ timeout: 15000 });
    await expect(freshEl).toBeVisible({ timeout: 15000 });
  });

  test("expiring item has visual expiry warning indicator", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // The badge carries its state in `data-expiry-state`, so the assertion
    // survives both the palette (warning is amber today) and the locale
    // (the date renders as 08/17/2026 under en-US, not as the ISO string).
    const expiryBadge = (name: string) =>
      page
        .getByTestId("item-row")
        .filter({ hasText: name })
        .first()
        .getByTestId("item-expiry");

    await expect(expiryBadge(expiringName)).toHaveAttribute(
      "data-expiry-state",
      "expiring",
      { timeout: 15000 },
    );
    // Contrast: the same badge on an item 30 days out must not warn, or the
    // assertion above would pass on a row that warns unconditionally.
    await expect(expiryBadge(freshName)).toHaveAttribute(
      "data-expiry-state",
      "ok",
    );
  });
});
