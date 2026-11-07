import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — Phase C: financial result (savings / margin).
 *
 * These tests prove that:
 *  - completing an order stores the financial result snapshot
 *    (unit_cost, reference_price, result per unit and per batch)
 *  - the production list shows the per-order result
 *  - Production's start aggregates the monthly result
 */

let api: ApiHelper;
let ctx: APIRequestContext;
let token: string;
let stamp: string;
let orderId: string;
let orderNumber: string;

test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
  ctx = await playwright.request.newContext({ baseURL });
  api = new ApiHelper(ctx);

  const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
  token = auth.access_token;
  await api.enableAllModules(token);

  // The worker index keeps two workers entering this hook in the same
  // millisecond from building one location name.
  stamp = `E2E-Result-${Date.now()}-w${testInfo.workerIndex}`;
  const output = await api.createProductTemplate(token, {
    name: `${stamp}-Jam`,
  });
  const ingredient = await api.createProductTemplate(token, {
    name: `${stamp}-Fruit`,
  });
  const sIn = await api.createStorage(token, { name: `${stamp}-In` });
  const sOut = await api.createStorage(token, { name: `${stamp}-Out` });

  // Stock: 10 kg fruit at the input location, bought at 2.50 a kilo. Without a
  // price the run would state no result at all: its cost would leave the fruit
  // out, and a margin against that cost would be overstated by exactly it.
  await api.seedStock(token, {
    product_template_id: ingredient.id,
    product_template_name: `${stamp}-Fruit`,
    location_id: sIn.id,
    quantity: 10,
    purchase_price: "2.50",
  });

  // Formula with a reference (store) price of 12.50; 1 kg fruit per batch.
  await api.createMakerRecipe(token, {
    output_template_id: output.id,
    name: `${stamp}-Formula`,
    batch_yield_qty: "1",
    reference_price: "12.50",
  });
  await api.createBomLine(token, {
    parent_template_id: output.id,
    child_template_id: ingredient.id,
    qty_per_batch: "1",
    unit: "kg",
  });

  // Plan 2 jars → complete them: 2 kg fruit at 2.50 → unit cost 2.50,
  // result per unit 12.50 − 2.50 = 10.00.
  const order = await api.createProductionOrder(token, {
    output_template_id: output.id,
    planned_qty: "2",
    output_location_id: sOut.id,
  });
  orderId = order.id;
  orderNumber = order.number;
  await api.completeProductionOrder(token, order.id);
});

test.afterAll(async () => {
  await ctx.dispose();
});

test.describe("Maker — financial result (Phase C)", () => {
  test("complete stores the result snapshot on the order", async () => {
    const resp = await ctx.get(`/api/v1/maker/production/orders/${orderId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();

    expect(body.status).toBe("COMPLETED");
    expect(body.reference_price_snapshot).toBe("12.50");
    expect(body.unit_cost_snapshot).toBe("2.5000");
    expect(body.result_per_unit).toBe("10.00");
    // One jar per batch.
    expect(body.result_per_batch).toBe("10.00");
  });

  test("production list shows the result column for completed orders", async ({
    page,
    authenticatedPage,
  }) => {
    // The first assertion after a goto waits for the whole first render, not
    // for one element: in a full run on a 2-CPU runner the dev server took 8 s
    // to serve the page's modules before the list query was even sent — past
    // the 5 s default, so the test failed while the server had answered nothing.
    await page.goto("/maker/production");
    // By the run's own number: a spec in another worker may plan a draft of
    // this product through the form, and the newest card comes first.
    const card = page
      .getByText(orderNumber, { exact: true })
      .locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]");
    // The result carries the organization's own name for it — savings on a
    // fresh stack, margin where someone switched it.
    await expect(card).toContainText(/Savings vs shop price|Margin/, {
      timeout: 15000,
    });
    // Currency symbol depends on the org's setting (PLN on a fresh stack,
    // USD on a hand-configured one) — assert the numbers, not the symbol.
    await expect(card).toContainText(/20\.00/);
    // The result per piece, in the output's own unit.
    await expect(card).toContainText(/10\.00 per pcs/);
  });

  test("production's start aggregates the monthly result", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/maker");
    const widget = page
      .locator("div.bg-surface-card", { hasText: /by month/ })
      .first();
    // Same first render as above: the card sits on Production's lazily
    // loaded start screen, and it fetches its data only once mounted.
    await expect(widget).toBeVisible({ timeout: 15000 });
    // The headline is a currency value aggregated from order snapshots
    // (exact value depends on org history — unit tests pin the math).
    // Assert digits, not a symbol: the currency follows the org setting.
    await expect(widget.locator(".text-2xl")).toContainText(/[\d.,]+/);
  });
});
