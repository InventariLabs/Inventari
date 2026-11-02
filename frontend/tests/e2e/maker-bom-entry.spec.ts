import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * BoM entry UX: from an item's edit modal, the maker module surfaces a
 * "Formula" button (item_edit_extra slot) that takes the operator to the
 * formula for that product — no UUID paste needed.
 *
 * Two destinations, because a product may not have a formula yet. The
 * button used to deep-link into `/maker/bom?parent=`, and when that screen
 * was removed the no-formula case — the common one — walked into a dead
 * route. It now opens the catalog's create sheet on that product.
 */
test.describe("Maker — BoM entry from item view", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
  });

  test.afterAll(async () => {
    await ctx.dispose();
  });

  /** An item backed by its own product template, visible in the items list. */
  async function seedItem(label: string) {
    const stamp = Date.now();
    const storage = await api.createStorageIdempotent(token, {
      name: `E2E-BoMEntry-Store-${stamp}`,
    });
    const name = `E2E-BoMEntry-${label}-${stamp}`;
    const template = await api.createProductTemplate(token, { name });
    await api.createItemForTemplate(token, {
      name,
      template_id: template.id,
      location_id: storage.id,
      quantity: 3,
    });
    return { name, templateId: template.id };
  }

  /** Open the item's edit dialog and press the maker slot button. */
  async function clickEntryLink(
    page: import("@playwright/test").Page,
    itemName: string,
  ) {
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const itemNameCell = page
      .getByTestId("item-name")
      .filter({ hasText: itemName });
    await expect(itemNameCell).toBeVisible({ timeout: 15000 });
    // A product's name opens its edit dialog directly.
    await itemNameCell.click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5000 });

    const entryLink = page.getByTestId("maker-bom-entry-link");
    await expect(entryLink).toBeVisible({ timeout: 5000 });
    await entryLink.click();
  }

  test("product without a formula: lands on the catalog, create sheet preselected", async ({
    page,
    authenticatedPage,
  }) => {
    const { name } = await seedItem("New");

    await clickEntryLink(page, name);

    await expect(page).toHaveURL(/\/maker$/, { timeout: 10000 });

    // The sheet is open on this product: the picker is already resolved
    // (hence the "change" button) and the name is defaulted from it.
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10000 });
    await expect(
      dialog.getByTestId("maker-recipe-create-change-product"),
    ).toBeVisible({ timeout: 5000 });
    await expect(dialog.getByTestId("maker-recipe-create-name")).toHaveValue(
      name,
    );

    // And it creates a formula for that product, ending on its detail page.
    await dialog.getByTestId("maker-recipe-create-submit").click();
    await expect(page).toHaveURL(/\/maker\/recipes\/[0-9a-f-]{36}$/, {
      timeout: 10000,
    });
  });

  test("product with a formula: goes straight to its formula card", async ({
    page,
    authenticatedPage,
  }) => {
    const { name, templateId } = await seedItem("Existing");
    const recipe = await api.createMakerRecipe(token, {
      output_template_id: templateId,
      name: `${name}-Formula`,
    });
    // The button reads the summary endpoint, which only reports templates
    // that have at least one line.
    const child = await api.createProductTemplate(token, {
      name: `${name}-Child`,
    });
    await api.createBomLine(token, {
      recipe_id: recipe.id,
      child_template_id: child.id,
      qty_per_batch: "1",
      unit: "kg",
    });

    await clickEntryLink(page, name);

    await expect(page).toHaveURL(new RegExp(`/maker/recipes/${recipe.id}$`), {
      timeout: 10000,
    });

    await api.deleteMakerRecipe(token, recipe.id).catch(() => {});
  });
});
