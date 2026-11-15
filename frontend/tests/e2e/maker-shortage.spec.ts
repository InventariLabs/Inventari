import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * A formula whose ingredients the records do not hold says so on arrival.
 *
 * The notice names the missing ingredient and offers the two ways out the
 * formula page owns: order it as a draft purchase order, or enter the stock
 * that is on the shelf (quantity and price). Both stay inside production;
 * the record the second one writes clears the notice.
 */
test.describe("Maker — a formula the records cannot cover", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string; name: string };
  let child: { id: string; name: string };
  let recipe: { id: string; name: string };

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);

    const stamp = `${Date.now()}-w${test.info().workerIndex}`;
    parent = await api.createProductTemplate(token, {
      name: `E2E-Stock-Parent-${stamp}`,
    });
    child = await api.createProductTemplate(token, {
      name: `E2E-Stock-Child-${stamp}`,
    });
    recipe = await api.createMakerRecipe(token, {
      output_template_id: parent.id,
      name: `E2E-Stock-Recipe-${stamp}`,
      batch_yield_qty: "1",
    });
    await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: child.id,
      qty_per_batch: "1",
      unit: "pcs",
    });
  });

  test.afterAll(async () => {
    await api.deleteMakerRecipe(token, recipe.id).catch(() => {});
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await ctx.dispose();
  });

  test("orders what is missing, then takes the stock the user has", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/recipes/${recipe.id}`);

    const notice = page.getByTestId("maker-recipe-shortage-notice");
    await expect(notice).toBeVisible({ timeout: 10000 });
    await expect(notice.getByText(child.name, { exact: true })).toBeVisible();

    // One click raises the order, and the toast names the document.
    await page.getByTestId("maker-recipe-order-shortage").click();
    await expect(
      page.getByText(/Draft purchase order \S+ created/),
    ).toBeVisible({ timeout: 10000 });

    // The stock that is actually on the shelf: quantity and what it cost.
    await page.getByTestId("maker-recipe-add-stock").click();
    // The row offers the shortfall rounded to the buying step where the
    // server can state one; the quantity is editable either way.
    const quantity = page.getByTestId("maker-add-stock-quantity");
    if ((await quantity.inputValue()) === "") await quantity.fill("1");
    const price = page.getByTestId("maker-add-stock-price");
    await expect(price).toHaveValue("");
    await price.fill("12.00");
    await page.getByTestId("maker-add-stock-save").click();

    await expect(page.getByText("Stock saved.")).toBeVisible({
      timeout: 10000,
    });
    // The batch is covered now, so the notice is gone and the badge says so.
    await expect(notice).toBeHidden({ timeout: 10000 });
    await expect(page.getByText("1 of 1 in stock")).toBeVisible({
      timeout: 10000,
    });
  });
});
