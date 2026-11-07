import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — Phase D: recipes → maker bridge ("cook a batch for stock").
 *
 * These tests prove that:
 *  - the culinary recipe detail page exposes the bridge button
 *  - the modal snapshots the culinary recipe into a maker recipe
 *    (source_recipe_id + source_snapshot_at stamped, BoM lines from
 *    template-linked ingredients only — free-text ingredients skipped)
 *  - a DRAFT production order is created against the snapshot recipe
 *  - the flow lands on the new production order detail page
 */

let api: ApiHelper;
let ctx: APIRequestContext;
let token: string;
let stamp: string;
let culinaryRecipeId: string;
let fruitTemplateId: string;
let outputTemplateId: string;
let outputStorageId: string;
let outputStorageName: string;

test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
  ctx = await playwright.request.newContext({ baseURL });
  api = new ApiHelper(ctx);

  const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
  token = auth.access_token;
  await api.enableAllModules(token);
  // Deterministic: other specs may leave WARN/BLOCK on the shared admin org.
  await api.patchMakerSettings(token, {
    create_on_shortage_strategy: "ALLOW",
  });

  // The worker index keeps two workers entering this hook in the same
  // millisecond from building one location name.
  stamp = `E2E-Bridge-${Date.now()}-w${testInfo.workerIndex}`;
  const output = await api.createProductTemplate(token, {
    name: `${stamp}-Jam`,
  });
  outputTemplateId = output.id;
  const fruit = await api.createProductTemplate(token, {
    name: `${stamp}-Fruit`,
  });
  fruitTemplateId = fruit.id;
  const sugar = await api.createProductTemplate(token, {
    name: `${stamp}-Sugar`,
  });
  const sIn = await api.createStorage(token, { name: `${stamp}-In` });
  const sOut = await api.createStorage(token, { name: `${stamp}-Out` });
  outputStorageId = sOut.id;
  outputStorageName = sOut.name;

  const culinary = await api.createRecipe(token, {
    name: `${stamp} Jam Recipe`,
    servings: 6,
    ingredients: [
      { name: "fruit", template_id: fruit.id, quantity: 2 },
      { name: "sugar", template_id: sugar.id, quantity: 1 },
      // Free-text ingredient without a template — must be skipped in the BoM.
      { name: "a pinch of love", quantity: 1 },
    ],
  });
  culinaryRecipeId = culinary.id;
  void sIn;
});

test.afterAll(async () => {
  await api.deleteRecipe(token, culinaryRecipeId).catch(() => {});
  await ctx.dispose();
});

test.describe("Maker — recipes → maker bridge (Phase D)", () => {
  // The three tests share beforeAll-seeded data and build on each other
  // (bridge → reuse → where-used), so the file must NOT be parallelized
  // despite fullyParallel: true in the config.
  test.describe.configure({ mode: "serial" });

  test("cooks a batch for stock end-to-end (recipe → modal → DRAFT order)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${culinaryRecipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const bridgeButton = page.getByTestId("cook-for-stock-button");
    await expect(bridgeButton).toBeVisible({ timeout: 10000 });
    await bridgeButton.click();

    const dialog = page.locator('[role="dialog"]').first();
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // Output product search → pick the seeded jam template.
    await dialog
      .getByTestId("cook-for-stock-product-search-input")
      .fill(`${stamp}-Jam`);
    // Portalled to document.body to escape the modal's overflow, so it is
    // not a descendant of the dialog — scope to the page.
    await page
      .getByTestId("cook-for-stock-product-search-result")
      .first()
      .click();

    // Scale 2 × servings (6) → planned output 12.
    await dialog.getByTestId("cook-for-stock-scale-input").fill("2");
    await expect(dialog.getByTestId("cook-for-stock-planned-qty")).toHaveText(
      "12",
    );
    // The plain <select> became a SearchableCombobox: a trigger button plus
    // a portalled popover, so the options are not descendants of the dialog.
    // The field was renamed after the destination — "To location".
    await dialog.getByRole("combobox", { name: /to location/i }).click();
    const storageSearch = page.getByPlaceholder(/search by name or path/i);
    await expect(storageSearch).toBeVisible({ timeout: 5000 });
    await storageSearch.fill(outputStorageName);
    await page
      .getByRole("button", { name: outputStorageName, exact: false })
      .last()
      .click();

    const orderResponsePromise = page.waitForResponse(
      (r) =>
        r.url().endsWith("/maker/production/orders") &&
        r.request().method() === "POST" &&
        r.ok(),
      { timeout: 15000 },
    );
    await dialog.getByTestId("cook-for-stock-submit").click();

    const orderBody = await orderResponsePromise.then((r) => r.json());
    expect(orderBody.status).toBe("DRAFT");
    expect(orderBody.output_template_id).toBe(outputTemplateId);
    expect(orderBody.output_location_id).toBe(outputStorageId);
    expect(orderBody.planned_qty).toBe("12.000");
    expect(orderBody.recipe_id).toBeTruthy();

    // Landed on the new production order detail page.
    await page.waitForURL(`**/maker/production/${orderBody.id}`, {
      timeout: 10000,
    });

    // The snapshot maker recipe is stamped and has exactly the
    // template-linked ingredients as BoM lines (free-text skipped).
    const recipe = await api.getMakerRecipe(token, orderBody.recipe_id);
    expect(recipe.source_recipe_id).toBe(culinaryRecipeId);
    expect(recipe.name).toBe(`${stamp} Jam Recipe`);
    expect(recipe.batch_yield_qty).toBe("6.0000");
    expect(recipe.lines).toHaveLength(2);
    const childIds = recipe.lines.map((l) => l.child_template_id);
    expect(childIds).toContain(fruitTemplateId);
    // A recipe line always has a unit (the recipe refuses one without), and the
    // BoM line keeps it: `createRecipe` gave both lines grams.
    expect(recipe.lines.map((l) => l.unit)).toEqual(["g", "g"]);

    // Snapshot is one-way: GET /maker/recipes/{id} carries the stamp; the
    // culinary recipe row is untouched (no back-reference exists by design).
    const detail = await api.getMakerRecipe(token, orderBody.recipe_id);
    expect(detail.id).toBe(recipe.id);
  });

  test("reusing the bridge for the same product reuses the snapshot recipe", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${culinaryRecipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await page.getByTestId("cook-for-stock-button").click();
    const dialog = page.locator('[role="dialog"]').first();
    await dialog
      .getByTestId("cook-for-stock-product-search-input")
      .fill(`${stamp}-Jam`);
    // Portalled to document.body to escape the modal's overflow, so it is
    // not a descendant of the dialog — scope to the page.
    await page
      .getByTestId("cook-for-stock-product-search-result")
      .first()
      .click();
    // The plain <select> became a SearchableCombobox (see the first test).
    // The field was renamed after the destination — "To location".
    await dialog.getByRole("combobox", { name: /to location/i }).click();
    const storageSearch = page.getByPlaceholder(/search by name or path/i);
    await expect(storageSearch).toBeVisible({ timeout: 5000 });
    await storageSearch.fill(outputStorageName);
    await page
      .getByRole("button", { name: outputStorageName, exact: false })
      .last()
      .click();
    const orderResponsePromise = page.waitForResponse(
      (r) =>
        r.url().endsWith("/maker/production/orders") &&
        r.request().method() === "POST" &&
        r.ok(),
      { timeout: 15000 },
    );
    await dialog.getByTestId("cook-for-stock-submit").click();
    const orderBody = await orderResponsePromise.then((r) => r.json());
    await page.waitForURL(`**/maker/production/${orderBody.id}`, {
      timeout: 10000,
    });

    // Same snapshot recipe id as the first test run — the backend reused it.
    const recipe = await api.getMakerRecipe(token, orderBody.recipe_id);
    expect(recipe.source_recipe_id).toBe(culinaryRecipeId);
    expect(recipe.lines).toHaveLength(2);
  });

  test("where-used reports the snapshot recipe for the ingredient (Phase E)", async ({
    authenticatedPage,
  }) => {
    // The fruit template is a direct ingredient of the snapshot recipe.
    const whereUsed = await api.whereUsed(token, fruitTemplateId);
    expect(whereUsed.items.length).toBeGreaterThan(0);
    const entry = whereUsed.items.find(
      (item) => item.output_template_id === outputTemplateId,
    );
    expect(entry).toBeTruthy();
    expect(entry?.qty_per_batch).toBe("2.0000");
    // The recipe line's own unit, as the bridge copied it.
    expect(entry?.unit).toBe("g");

    // A template used nowhere returns an empty list.
    const unused = await api.createProductTemplate(token, {
      name: `${stamp}-Unused`,
    });
    const empty = await api.whereUsed(token, unused.id);
    expect(empty.items).toEqual([]);
  });
});
