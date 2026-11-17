import { test, expect } from "./fixtures/auth";
import type { APIRequestContext } from "@playwright/test";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — a run that is started and finished later, on screen.
 *
 * Starting a run chooses its ingredient batches as completing one in one step
 * does, and a portion takes the best-before the person gives it. The syrup
 * the jam is made of sits in two batches, so the choice is a real one: the
 * run takes the batch picked in the Start dialog, not the default draw.
 */

test.describe.configure({ mode: "serial" });

test.describe("Maker — a started run chooses its batches", () => {
  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  let syrupId: string;
  let orderId: string;
  let chosenSyrupBatch: { id: string; name: string };
  const cleanup: Array<() => Promise<unknown>> = [];

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);

    const stamp = `${Date.now()}-w${testInfo.workerIndex}`;
    const sugar = await api.createProductTemplate(token, {
      name: `E2E-SR-Sugar-${stamp}`,
    });
    const syrup = await api.createProductTemplate(token, {
      name: `E2E-SR-Syrup-${stamp}`,
    });
    const jam = await api.createProductTemplate(token, {
      name: `E2E-SR-Jam-${stamp}`,
    });
    syrupId = syrup.id;
    // The jam keeps for a month: a portion proposes that date.
    const shelfLife = await ctx.put(
      `/api/v1/maker/production/shelf-lives/${jam.id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { shelf_life_days: 30 },
      },
    );
    expect(shelfLife.ok(), await shelfLife.text()).toBe(true);
    const shelf = await api.createStorage(token, {
      name: `E2E-SR-Shelf-${stamp}`,
    });
    const sugarStock = await api.seedStock(token, {
      product_template_id: sugar.id,
      product_template_name: sugar.name,
      location_id: shelf.id,
      quantity: 100,
    });
    const syrupLine = await api.createBomLine(token, {
      parent_template_id: syrup.id,
      child_template_id: sugar.id,
      qty_per_batch: "2",
      unit: "kg",
    });
    const jamLine = await api.createBomLine(token, {
      parent_template_id: jam.id,
      child_template_id: syrup.id,
      qty_per_batch: "2",
      unit: "kg",
    });

    // Two batches of syrup, each enough for the whole jam run.
    for (let n = 0; n < 2; n++) {
      const run = await api.createProductionOrder(token, {
        output_template_id: syrup.id,
        planned_qty: "10",
        output_location_id: shelf.id,
      });
      await api.completeProductionOrder(token, run.id);
    }
    const lots = await ctx.get(
      `/api/v1/stock-lots?product_template_id=${syrup.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const batches = (
      (await lots.json()) as { items: Array<{ id: string; name: string }> }
    ).items.sort((a, b) => a.name.localeCompare(b.name));
    expect(batches).toHaveLength(2);
    chosenSyrupBatch = batches[1];
    // With its own formula gone the syrup is a product kept in two batches.
    await api.deleteBomLine(token, syrupLine.id);

    const draft = await api.createProductionOrder(token, {
      output_template_id: jam.id,
      planned_qty: "3",
      output_location_id: shelf.id,
    });
    orderId = draft.id;
    cleanup.push(
      () => api.deleteBomLine(token, jamLine.id),
      () => api.deleteItem(token, sugarStock.item_id),
    );
  });

  test.afterAll(async () => {
    for (const undo of cleanup) await undo().catch(() => {});
    await ctx.dispose();
  });

  test("starting the run takes the batch picked in the Start dialog", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/production/${orderId}`);
    await page.getByTestId("maker-detail-start-button").click();

    const dialog = page.getByRole("alertdialog");
    const select = dialog.getByTestId(`maker-batch-select-${syrupId}`);
    await expect(select).toBeVisible({ timeout: 15000 });
    await expect(select).toHaveValue("");
    await select.selectOption(chosenSyrupBatch.id);

    const started = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith(`/orders/${orderId}/start`),
    );
    await dialog.getByRole("button", { name: "Start run" }).click();
    const body = (await started).postDataJSON();
    expect(body.ingredient_lots).toEqual([
      expect.objectContaining({
        template_id: syrupId,
        lot_id: chosenSyrupBatch.id,
      }),
    ]);
    await expect(page.getByTestId("maker-portion-qty-input")).toBeVisible({
      timeout: 15000,
    });

    const moves = await ctx.get(
      `/api/v1/maker/production/orders/${orderId}/stock-moves`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const taken = (
      (await moves.json()) as {
        items: Array<{
          product_template_id: string;
          from_location_id: string | null;
          lot_code: string | null;
        }>;
      }
    ).items.filter(
      (move) => move.product_template_id === syrupId && move.from_location_id,
    );
    expect(taken.length).toBeGreaterThan(0);
    expect(taken.every((m) => m.lot_code === chosenSyrupBatch.name)).toBe(true);
  });

  test("a portion is put on the shelf with the best-before proposed for it", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/production/${orderId}`);
    await page.getByTestId("maker-portion-qty-input").fill("1");
    await page.getByTestId("maker-portion-lot-input").fill("E2E-PORTION");

    const added = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith(`/orders/${orderId}/portions`),
    );
    await page.getByTestId("maker-portion-add-button").click();
    const body = (await added).postDataJSON();
    expect(body.qty).toBe("1");
    expect(body.best_before).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await expect(page.getByText("Output so far")).toBeVisible();
    await expect(page.getByTestId("maker-output-batch-code")).toContainText(
      "E2E-PORTION",
      { timeout: 15000 },
    );
  });
});
