import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * "Recently visited" fills from the record pages a person comes back to — a
 * product, an asset, a recipe — and reads the same in the launcher's panel and
 * in the command palette, newest first, one entry per record.
 *
 * The hook that records a visit and the two lists that read it each have a
 * unit test; this walks a person through all three pages and then reads both
 * lists, which no unit test does. The list lives in the browser, so every test
 * starts from an empty one.
 */
test("the launcher and the command palette list the records visited, newest first", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const request = await playwright.request.newContext({ baseURL });
  const api = new ApiHelper(request);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  await api.enableAllModules(token);
  const uid = `${Date.now().toString(36)}-w${testInfo.workerIndex}`;
  const storage = await api.createStorageIdempotent(token, {
    name: `E2E-Visited-Shelf-${uid}`,
  });
  const productName = `E2E-Visited-Product-${uid}`;
  const assetName = `E2E-Visited-Asset-${uid}`;
  const recipeName = `E2E-Visited-Recipe-${uid}`;
  const product = await api.createItem(token, {
    name: productName,
    quantity: 1,
    location_id: storage.id,
  });
  const asset = await api.createEquipmentItem(token, {
    name: assetName,
    quantity: 1,
    location_id: storage.id,
    metadata: { equipment: { equipment_status: "AVAILABLE" } },
  });
  const recipe = await api.createRecipe(token, {
    name: recipeName,
    servings: 2,
    ingredients: [],
  });

  try {
    // Nothing visited yet: no panel at all.
    await page.goto("/launcher");
    await expect(
      page.getByRole("heading", { name: "Recently visited" }),
    ).toHaveCount(0);

    for (const [path, name] of [
      [`/inventory/items/${product.id}`, productName],
      [`/equipment/${asset.id}`, assetName],
      [`/recipes/${recipe.id}`, recipeName],
    ] as const) {
      await page.goto(path);
      await expect(page.getByText(name).first()).toBeVisible({
        timeout: 15000,
      });
    }

    // The launcher's panel: the last visit on top.
    await page.goto("/launcher");
    const panel = page
      .getByRole("region", { name: "Recently visited" })
      .or(
        page
          .getByRole("heading", { name: "Recently visited" })
          .locator("xpath=ancestor::section[1]"),
      );
    const entries = panel.getByRole("link");
    // Each entry names the record and the module it belongs to, the way the
    // module's own tile does (the first letter is the entry's icon).
    const panelEntry = (name: string, module: string) =>
      new RegExp(`^.${name}${module}$`);
    await expect(entries).toHaveText([
      panelEntry(recipeName, "Recipes"),
      panelEntry(assetName, "Equipment Tracking"),
      panelEntry(productName, "Inventory"),
    ]);

    // A second visit moves the record to the top instead of adding it again.
    await page.goto(`/inventory/items/${product.id}`);
    await expect(page.getByText(productName).first()).toBeVisible();
    await page.goto("/launcher");
    await expect(entries).toHaveText([
      panelEntry(productName, "Inventory"),
      panelEntry(recipeName, "Recipes"),
      panelEntry(assetName, "Equipment Tracking"),
    ]);

    // The command palette reads the same list.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog").or(page.locator("[cmdk-root]"));
    const group = palette
      .locator("[cmdk-group]")
      .filter({ hasText: "Recently visited" });
    await expect(group.locator("[cmdk-item]")).toHaveText([
      new RegExp(`^${productName}Inventory$`),
      new RegExp(`^${recipeName}Recipes$`),
      new RegExp(`^${assetName}Equipment Tracking$`),
    ]);

    // Choosing one goes to its page.
    await group.locator("[cmdk-item]", { hasText: assetName }).click();
    await expect(page).toHaveURL(new RegExp(`/equipment/${asset.id}`));
    await expect(page.getByText(assetName).first()).toBeVisible();

    // And the panel's own link goes to the same page.
    await page.goto("/launcher");
    await panel.getByRole("link", { name: new RegExp(recipeName) }).click();
    await expect(page).toHaveURL(new RegExp(`/recipes/${recipe.id}`));
  } finally {
    await api.deleteItem(token, product.id).catch(() => {});
    await api.deleteItem(token, asset.id).catch(() => {});
    await api.deleteRecipe(token, recipe.id).catch(() => {});
    await request.dispose();
  }
});
