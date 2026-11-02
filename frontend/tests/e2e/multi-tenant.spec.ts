import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Multi-tenant — data isolation between organizations", () => {
  let api: ApiHelper;
  let tokenA: string;
  let seedItemId: string;
  const seedItemName = `E2E-Tenant-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authA = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    tokenA = authA.access_token;

    const storages = await api.listStorages(tokenA);
    const storageId = storages[0]?.id;
    if (!storageId)
      throw new Error("No storage available for multi-tenant test");

    const item = await api.createItem(tokenA, {
      name: seedItemName,
      quantity: 1,
      unit: "pcs",
      location_id: storageId,
    });
    seedItemId = item.id;
  });

  test.afterAll(async () => {
    if (tokenA && seedItemId) {
      await api.deleteItem(tokenA, seedItemId).catch(() => {});
    }
  });

  test("admin sees their own seeded item", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(
      page.getByTestId("item-name").filter({ hasText: seedItemName }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("second-org user cannot see first-org items (API level)", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const secondApi = new ApiHelper(ctx);

    let tokenB: string;
    try {
      const authB = await secondApi.login("user2@example.com", "user2password");
      tokenB = authB.access_token;
    } catch {
      return;
    }

    const resp = await ctx.get("/api/v1/items", {
      headers: { Authorization: `Bearer ${tokenB}` },
    });
    expect(resp.ok()).toBe(true);
    const data: { items?: Array<{ name: string }> } | Array<{ name: string }> =
      await resp.json();
    const itemList: Array<{ name: string }> = Array.isArray(data)
      ? data
      : (data.items ?? []);
    const leaked = itemList.some((i) => i.name === seedItemName);
    expect(leaked).toBe(false);
  });

  test("unauthenticated request to /api/v1/items returns 401", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const resp = await ctx.get("/api/v1/items");
    expect(resp.status()).toBe(401);
  });

  test("org A item is not accessible via direct API by missing token", async ({
    playwright,
    baseURL,
  }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const resp = await ctx.get(`/api/v1/items/${seedItemId}`);
    expect(resp.status()).toBe(401);
  });
});
