import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { isoDay, pickDay } from "./helpers/date-picker";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The production plan: planned runs by day, each marked against the shelf the
 * runs before it leave, the one list of what they need, and the two buttons
 * that act on what is missing.
 *
 * Every piece has a component test; this walks the wiring between the filters
 * the page sends, the calendar it draws and the actions it offers — which
 * those tests cannot see. The runs, products and storage are named for this
 * spec's stamp, so other specs' runs on the same screen are never asserted on.
 */

test.describe("Maker — the production plan", () => {
  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  let stamp: string;
  const runIds: string[] = [];
  const recipeIds: string[] = [];
  const templateIds: string[] = [];
  let cake: { id: string; name: string };
  let flour: { id: string; name: string };
  let dough: { id: string; name: string };
  let outputId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
    stamp = `${Date.now().toString(36)}-w${test.info().workerIndex}`;

    const named = async (label: string) => {
      const name = `E2E-Plan-${label}-${stamp}`;
      const made = await api.createProductTemplate(token, { name });
      templateIds.push(made.id);
      return { id: made.id, name };
    };
    cake = await named("Cake");
    flour = await named("Flour");
    dough = await named("Dough");
    outputId = (
      await api.createStorage(token, { name: `E2E-Plan-Shelf-${stamp}` })
    ).id;

    // The cake needs one flour and one dough; the dough has a recipe of its
    // own, so the plan marks it as something to make, not to buy.
    const cakeRecipe = await api.createMakerRecipe(token, {
      output_template_id: cake.id,
      name: `E2E-Plan-CakeRecipe-${stamp}`,
    });
    recipeIds.push(cakeRecipe.id);
    for (const child of [flour, dough]) {
      await api.createBomLine(token, {
        recipe_id: cakeRecipe.id,
        child_template_id: child.id,
        qty_per_batch: "1",
        unit: "pcs",
      });
    }
    const doughRecipe = await api.createMakerRecipe(token, {
      output_template_id: dough.id,
      name: `E2E-Plan-DoughRecipe-${stamp}`,
    });
    recipeIds.push(doughRecipe.id);
    await api.createBomLine(token, {
      recipe_id: doughRecipe.id,
      child_template_id: flour.id,
      qty_per_batch: "1",
      unit: "pcs",
    });

    // One flour and one dough on the shelf: they cover the first cake and
    // leave the second one short.
    for (const stocked of [flour, dough]) {
      await api.seedStock(token, {
        product_template_id: stocked.id,
        product_template_name: stocked.name,
        location_id: outputId,
        quantity: 1,
      });
    }
    // The first cake is planned for today, the second for the day after.
    for (const offset of [0, 1]) {
      const run = await api.createProductionOrder(token, {
        output_template_id: cake.id,
        planned_qty: 1,
        output_location_id: outputId,
        production_date: isoDay(offset),
        confirm_shortage: true,
      });
      runIds.push(run.id);
    }
  });

  test.afterAll(async () => {
    for (const id of runIds) {
      await api.cancelProductionOrder(token, id).catch(() => {});
    }
    await ctx.dispose();
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/maker/production/plan");
    await expect(
      page.getByRole("heading", { level: 1, name: "Production plan" }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("draws the planned runs on their days, each against the shelf", async ({
    page,
  }) => {
    // Other specs' runs share the days: this spec's run is the list item
    // that carries its own product's name.
    const runOn = (offset: number) =>
      page
        .getByTestId(`maker-plan-day-${isoDay(offset)}`)
        .getByRole("listitem")
        .filter({ has: page.getByRole("link", { name: cake.name }) });

    const first = runOn(0);
    await expect(first).toBeVisible({ timeout: 15000 });
    // The shelf holds one flour and one dough: it covers the first run...
    await expect(first.getByTestId("maker-order-coverage")).toHaveText(
      "Covered",
    );
    // ...and what that run leaves does not cover the second one. A week that
    // ends today shows the second run on the next page, not here.
    if ((await page.getByTestId(`maker-plan-day-${isoDay(1)}`).count()) > 0) {
      const second = runOn(1);
      await expect(second).toBeVisible();
      await expect(second.getByTestId("maker-order-coverage")).toHaveText(
        "Short",
      );
    }
  });

  test("the period buttons move the window and the range says so", async ({
    page,
  }) => {
    const range = page.getByTestId("maker-plan-range");
    const week = await range.innerText();

    await page.getByRole("button", { name: "Next period" }).click();
    await expect(range).not.toHaveText(week);
    // Today's runs are not in next week's window.
    await expect(page.getByTestId(`maker-plan-day-${isoDay(0)}`)).toHaveCount(0);

    await page.getByRole("button", { name: "Previous period" }).click();
    await expect(range).toHaveText(week);

    await page.getByRole("button", { name: "Month", exact: true }).click();
    await expect(page.getByRole("button", { name: "Month" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(range).not.toHaveText(week);
    await expect(
      page
        .getByTestId(`maker-plan-day-${isoDay(0)}`)
        .getByRole("link", { name: cake.name }),
    ).toBeVisible();
  });

  test("moves a run to another day, and the run keeps the new day", async ({
    page,
  }) => {
    const todays = page.getByTestId(`maker-plan-day-${isoDay(0)}`);
    await todays
      .getByRole("button", { name: `Move ${cake.name} to another day` })
      .click();
    const sheet = page.getByRole("dialog", { name: `Move ${cake.name}` });
    await expect(sheet.getByText(/^Planned for .+ now\.$/)).toBeVisible();
    // Nothing to save until another day is chosen.
    await expect(sheet.getByRole("button", { name: "Move", exact: true })).toBeDisabled();

    const target = isoDay(2);
    await pickDay(page, sheet.getByRole("combobox", { name: /new day/i }), target);
    await sheet.getByRole("button", { name: "Move", exact: true }).click();
    await expect(sheet).toBeHidden();

    // Read it back: the run the plan showed today is on the new day.
    const moved = (await api.listProductionOrders(token)).find(
      (run) => run.id === runIds[0],
    ) as { production_date?: string } | undefined;
    expect(moved?.production_date).toBe(target);

    // Put it back, so the next test meets the plan as seeded.
    await api.request.patch(`/api/v1/maker/production/orders/${runIds[0]}`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { production_date: isoDay(0) },
    });
  });

  test("lists what the runs need, and plans the runs of what is missing", async ({
    page,
  }) => {
    const needs = page.getByTestId("maker-needs-table");
    const flourRow = needs.getByRole("row", { name: new RegExp(flour.name) });
    const doughRow = needs.getByRole("row", { name: new RegExp(dough.name) });
    await expect(flourRow).toBeVisible({ timeout: 15000 });
    // The dough has a recipe of its own: it is to be made, not bought.
    await expect(doughRow.getByText("Make", { exact: true })).toBeVisible();
    await expect(flourRow.getByText("Make", { exact: true })).toHaveCount(0);

    const doughRuns = async () =>
      api.listProductionOrders(token, {
        status: "DRAFT",
        output_template_id: dough.id,
      });
    expect(await doughRuns()).toHaveLength(0);
    await page.getByTestId("maker-plan-intermediates").click();
    await expect(page.getByText(/\d+ runs? planned/)).toBeVisible({
      timeout: 15000,
    });
    // The missing dough is now a run of its own, ready to be made.
    const planned = await doughRuns();
    expect(planned.length).toBeGreaterThan(0);
    runIds.push(...planned.map((run) => run.id));
  });

  test("orders what is missing: an ingredient no supplier offers lands on the shopping list", async ({
    page,
  }) => {
    const button = page.getByTestId("maker-order-missing");
    await expect(button).toBeVisible({ timeout: 15000 });
    await button.click();
    // Nothing prices the flour, so no draft order can be placed for it.
    await expect(
      page.getByText(/ingredients? put on the shopping list/),
    ).toBeVisible({ timeout: 15000 });

    // Read back: the flour is on a list as the production plan's item, with
    // a quantity.
    const headers = { Authorization: `Bearer ${token}` };
    const lists = await api.listShoppingLists(token);
    const listed: Array<{ listId: string; itemId: string; quantity: string }> =
      [];
    for (const list of lists) {
      const read = await ctx.get(`/api/v1/shopping-lists/${list.id}`, {
        headers,
      });
      const body = (await read.json()) as {
        items: Array<{
          id: string;
          template_id: string | null;
          source: string;
          quantity: string;
        }>;
      };
      for (const item of body.items) {
        if (item.template_id === flour.id) {
          listed.push({
            listId: list.id,
            itemId: item.id,
            quantity: item.quantity,
          });
          expect(item.source).toBe("production");
        }
      }
    }
    expect(listed).toHaveLength(1);
    expect(Number(listed[0].quantity)).toBeGreaterThan(0);
    await ctx.delete(
      `/api/v1/shopping-lists/${listed[0].listId}/items/${listed[0].itemId}`,
      { headers },
    );
  });
});
