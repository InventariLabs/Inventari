import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — recipe catalog / formula detail (new IA) + legacy BoM editor.
 *
 * The first describe covers the new catalog flow: seeded formula renders as
 * a card, cards open /maker/recipes/<id>, the Composition tab lists
 * ingredient names (not UUIDs), in-place line edits persist, the "New
 * formula" sheet creates a formula and navigates to its detail, and a bare
 * /maker/bom redirects to the catalog.
 *
 * The second describe keeps the legacy line editor tests behind the
 * ?parent= deep link (the only supported entry point): add-line persistence,
 * qty<=0 validation toast, and formula deletion.
 *
 * The third describe keeps the pure API invariants, updated for the
 * qty_per_unit → qty_per_batch rename.
 */

test.describe("Maker — recipe catalog & formula detail", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string; name: string };
  let seedChild: { id: string; name: string };
  let recipe: { id: string; name: string };

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);

    const stamp = `${Date.now()}-w${test.info().workerIndex}`;
    parent = await api.createProductTemplate(token, {
      name: `E2E-Maker-Parent-${stamp}`,
    });
    seedChild = await api.createProductTemplate(token, {
      name: `E2E-Maker-Child-${stamp}`,
    });
    // Seed a formula via the new recipes API, then give it one ingredient
    // line through the legacy BoM adapter.
    recipe = await api.createMakerRecipe(token, {
      output_template_id: parent.id,
      name: `E2E-Maker-Recipe-${stamp}`,
      batch_yield_qty: "2",
    });
    await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: seedChild.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });
  });

  test.afterAll(async () => {
    await api.deleteMakerRecipe(token, recipe.id).catch(() => {});
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await ctx.dispose();
  });

  test("catalog renders the seeded formula as a card", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/maker");
    await expect(
      page.getByRole("heading", { level: 1, name: /bills of materials/i }),
    ).toBeVisible({ timeout: 10000 });
    // Card shows the formula name, the output product name and the
    // ingredient count.
    await expect(
      page.getByText(recipe.name, { exact: true }).first(),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByText(parent.name, { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText("1 ingredient", { exact: true }).first(),
    ).toBeVisible();
  });

  test("clicking a card navigates to the formula detail page", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/maker");
    await page.getByText(recipe.name, { exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/maker/recipes/${recipe.id}`), {
      timeout: 10000,
    });
    // Header (h1) and summary card (h2) both show the formula name.
    await expect(
      page.getByRole("heading", { level: 1, name: recipe.name }),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByRole("heading", { level: 2, name: recipe.name }),
    ).toBeVisible();
  });

  test("detail Composition tab lists ingredient names, not raw UUIDs", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/recipes/${recipe.id}`);
    await expect(page.getByText(seedChild.name, { exact: true })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText(seedChild.id, { exact: true })).toHaveCount(0);
  });

  test("editing a line qty in the Composition tab persists (PATCH bom-line)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/recipes/${recipe.id}`);
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Qty per batch").fill("3.5");
    const savePromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/maker/recipes/${recipe.id}/bom-lines/`) &&
        r.request().method() === "PATCH" &&
        r.ok(),
      { timeout: 15000 },
    );
    await page.getByRole("button", { name: "Save" }).click();
    await savePromise;

    // Backend confirmation via the recipe detail API.
    const detail = await api.getMakerRecipe(token, recipe.id);
    const line = detail.lines.find((l) => l.child_template_id === seedChild.id);
    expect(line).toBeTruthy();
    expect(line!.qty_per_batch).toBe("3.5000");

    // Restore the original qty so other tests see a clean state.
    if (line) {
      await ctx.patch(
        `/api/v1/maker/recipes/${recipe.id}/bom-lines/${line.id}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          data: { qty_per_batch: "1" },
        },
      );
    }
  });

  test("bare /maker/bom redirects to the recipe catalog", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/maker/bom");
    await expect(page).toHaveURL(/\/maker$/, { timeout: 10000 });
    await expect(
      page.getByRole("heading", { level: 1, name: /bills of materials/i }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("'New formula' sheet creates a formula and navigates to its detail", async ({
    page,
    authenticatedPage,
  }) => {
    const product = await api.createProductTemplate(token, {
      name: `E2E-Maker-Create-${Date.now()}`,
    });

    await page.goto("/maker");
    await page.getByRole("button", { name: /new bom/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // The search is debounced and answered over the network; wait for the
    // search call itself, then for the result row. Waiting only on the row
    // made this flaky when the response was slow (the 5s window ran out).
    const searchResponse = page.waitForResponse(
      (r) =>
        r.url().includes("/items/product-templates") &&
        r.request().method() === "GET" &&
        r.ok(),
      { timeout: 10000 },
    );
    await dialog
      .getByTestId("maker-recipe-create-product-input")
      .fill(product.name);
    await searchResponse;
    // The result list is portalled to document.body so it can escape the
    // sheet's overflow — scope this to the page, not to the dialog. Filter
    // by name: an earlier (empty-query) response can satisfy the wait above
    // before the row for this product has rendered.
    const result = page
      .getByTestId("maker-recipe-create-product-result")
      .filter({ hasText: product.name })
      .first();
    await expect(result).toBeVisible({ timeout: 10000 });
    await result.click();

    // Selecting the product pre-fills the formula name — submit directly.
    await dialog.getByTestId("maker-recipe-create-submit").click();

    // Success navigates to the new formula's detail page.
    await expect(page).toHaveURL(/\/maker\/recipes\//, { timeout: 10000 });
    const idMatch = page.url().match(/\/maker\/recipes\/([0-9a-f-]+)/);
    expect(idMatch).not.toBeNull();
    await expect(
      page.getByRole("heading", { name: product.name }).first(),
    ).toBeVisible({ timeout: 10000 });

    if (idMatch) {
      await api.deleteMakerRecipe(token, idMatch[1]).catch(() => {});
    }
  });
});

test.describe("Maker — composing a formula (Composition tab)", () => {
  // What the removed /maker/bom editor used to cover, on the screen that
  // replaced it: add an ingredient, refuse a non-positive qty, delete the
  // formula. The old editor addressed a *product* and always wrote to its
  // default formula; these address the formula on screen.
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

  /** A product plus an empty formula for it, and one product to add as a line. */
  async function seedFormula(label: string) {
    const stamp = Date.now();
    const parent = await api.createProductTemplate(token, {
      name: `E2E-Maker-${label}-${stamp}`,
    });
    const child = await api.createProductTemplate(token, {
      name: `E2E-Maker-${label}Child-${stamp}`,
    });
    const recipe = await api.createMakerRecipe(token, {
      output_template_id: parent.id,
      name: `E2E-Maker-${label}Formula-${stamp}`,
    });
    return { parent, child, recipe };
  }

  test("adds an ingredient via the composition form; persists via API", async ({
    page,
    authenticatedPage,
  }) => {
    const { parent, child, recipe } = await seedFormula("Add");

    await page.goto(`/maker/recipes/${recipe.id}`);
    const search = page.getByTestId("maker-composition-child-search-input");
    await expect(search).toBeVisible({ timeout: 10000 });
    await search.fill(child.name);
    await expect(
      page.getByTestId("maker-composition-child-search-result").first(),
    ).toBeVisible({ timeout: 5000 });
    await page
      .getByTestId("maker-composition-child-search-result")
      .first()
      .click();
    await expect(
      page.getByTestId("maker-composition-child-selected"),
    ).toBeVisible({ timeout: 5000 });

    await page.getByTestId("maker-composition-qty-input").fill("2.5");
    const posted = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/maker/recipes/${recipe.id}/bom-lines`) &&
        r.request().method() === "POST" &&
        r.ok(),
      { timeout: 15000 },
    );
    await page.getByTestId("maker-composition-add-line").click();
    await posted;

    // Backend confirmation: the line landed on *this* formula.
    const detail = await api.getMakerRecipe(token, recipe.id);
    const created = detail.lines.find((l) => l.child_template_id === child.id);
    expect(created).toBeTruthy();
    expect(created!.qty_per_batch).toBe("2.5000");

    const lines = await api.listBomLines(token, parent.id);
    expect(lines.items.some((l) => l.child_template_id === child.id)).toBe(
      true,
    );

    await api.deleteMakerRecipe(token, recipe.id).catch(() => {});
  });

  test("qty <= 0 keeps the add button disabled", async ({
    page,
    authenticatedPage,
  }) => {
    const { child, recipe } = await seedFormula("Qty");

    await page.goto(`/maker/recipes/${recipe.id}`);
    const search = page.getByTestId("maker-composition-child-search-input");
    await expect(search).toBeVisible({ timeout: 10000 });
    await search.fill(child.name);
    await expect(
      page.getByTestId("maker-composition-child-search-result").first(),
    ).toBeVisible({ timeout: 5000 });
    await page
      .getByTestId("maker-composition-child-search-result")
      .first()
      .click();
    await expect(
      page.getByTestId("maker-composition-child-selected"),
    ).toBeVisible({ timeout: 5000 });

    // The legacy form accepted the click and answered with a toast; this one
    // refuses to arm the button, so the bad request is never sent.
    await page.getByTestId("maker-composition-qty-input").fill("0");
    await expect(page.getByTestId("maker-composition-add-line")).toBeDisabled();

    await page.getByTestId("maker-composition-qty-input").fill("1");
    await expect(page.getByTestId("maker-composition-add-line")).toBeEnabled();

    await api.deleteMakerRecipe(token, recipe.id).catch(() => {});
  });

  test("deleting a formula removes it and returns to the catalog", async ({
    page,
    authenticatedPage,
  }) => {
    const { parent, child, recipe } = await seedFormula("Del");
    await api.createBomLine(token, {
      recipe_id: recipe.id,
      child_template_id: child.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });

    await page.goto(`/maker/recipes/${recipe.id}`);
    await expect(page.getByTestId("maker-recipe-delete")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("maker-recipe-delete").click();
    const dlg = page.locator('[role="alertdialog"]').last();
    await expect(dlg).toBeVisible({ timeout: 5000 });
    await dlg.getByRole("button", { name: /delete bom/i }).click();

    await expect(page).toHaveURL(/\/maker$/, { timeout: 10000 });

    // Unlike the legacy delete, which only cleared the lines and left the
    // formula row behind, this removes the formula itself.
    const lines = await api.listBomLines(token, parent.id);
    expect(lines.items).toHaveLength(0);
    const gone = await ctx.get(`/api/v1/maker/recipes/${recipe.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(gone.status()).toBe(404);
  });
});

test.describe("Maker — BoM: backend invariants (API)", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string };
  let childA: { id: string };
  let childB: { id: string };
  let recipeId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    parent = await api.createProductTemplate(token, {
      name: `E2E-BoM-APIParent-${Date.now()}`,
    });
    childA = await api.createProductTemplate(token, {
      name: `E2E-BoM-APIChildA-${Date.now()}`,
    });
    childB = await api.createProductTemplate(token, {
      name: `E2E-BoM-APIChildB-${Date.now()}`,
    });
    // Lines belong to a formula; the product-level POST /maker/bom is gone.
    recipeId = await api.resolveDefaultRecipeId(token, parent.id);
  });

  test.afterAll(async () => {
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await ctx.dispose();
  });

  test("validates qty_per_batch > 0", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: childA.id,
        qty_per_batch: "0",
        unit: "kg",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("validates unit is non-empty", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: childA.id,
        qty_per_batch: "1",
        unit: "",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("rejects self-parent (parent==child)", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: parent.id,
        qty_per_batch: "1",
        unit: "kg",
      },
    });
    expect(resp.status()).toBe(400);
  });

  test("UNIQUE(recipe, child) constraint enforced", async () => {
    await api.createBomLine(token, {
      recipe_id: recipeId,
      child_template_id: childA.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });

    const dup = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: childA.id,
        qty_per_batch: "2",
        unit: "kg",
      },
    });
    // 409, not the 400 the removed adapter returned: a duplicate ingredient
    // is a conflict, and the per-formula endpoint says so.
    expect(dup.status()).toBe(409);
  });

  test("move: cycle prevention across move endpoint", async () => {
    // Setup: parent -> A, A -> B (so tree is parent/A/B)
    // Make this idempotent: delete any existing lines first.
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await api.deleteAllBomLinesForTemplate(token, childA.id).catch(() => {});

    const lineParentToA = await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: childA.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });
    const lineAtoB = await api.createBomLine(token, {
      parent_template_id: childA.id,
      child_template_id: childB.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });

    // Attempt to move parent->A under its grandchild B (would create cycle)
    const cycleResp = await ctx.post(
      `/api/v1/maker/bom/${lineParentToA.id}/move`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { new_parent_template_id: childB.id },
      },
    );
    expect(cycleResp.status()).toBe(400);

    // Valid move: reparent lineAtoB up to parent (allowed)
    const moveResp = await ctx.post(`/api/v1/maker/bom/${lineAtoB.id}/move`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { new_parent_template_id: parent.id },
    });
    expect(moveResp.ok()).toBeTruthy();
  });

  test("tree endpoint returns multi-level structure", async () => {
    // Self-contained setup so the test does not depend on the previous
    // "move" test's state (parallel workers can otherwise clear parent
    // lines via deleteAllBomLinesForTemplate between the two tests).
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await api.deleteAllBomLinesForTemplate(token, childA.id).catch(() => {});
    await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: childA.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });
    await api.createBomLine(token, {
      parent_template_id: childA.id,
      child_template_id: childB.id,
      qty_per_batch: "1",
      // The product is kept in pieces (the default unit): a line in kg is
      // refused when it is edited, because kg cannot be read as pcs.
      unit: "pcs",
    });

    const tree = (await api.getBomTree(token, parent.id)) as {
      root: { children: unknown[] };
    };
    expect(Array.isArray(tree.root.children)).toBeTruthy();
    expect(tree.root.children.length).toBeGreaterThanOrEqual(1);
  });

  test("DELETE /maker/recipes/{id} removes the formula", async () => {
    const tpl = await api.createProductTemplate(token, {
      name: `E2E-Maker-RecDel-${Date.now()}`,
    });
    const rec = await api.createMakerRecipe(token, {
      output_template_id: tpl.id,
      name: `E2E-Maker-RecDel-${Date.now()}`,
    });

    // Present before…
    const before = await ctx.get(`/api/v1/maker/recipes/${rec.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(before.status()).toBe(200);

    await api.deleteMakerRecipe(token, rec.id);

    // …gone after.
    const after = await ctx.get(`/api/v1/maker/recipes/${rec.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(after.status()).toBe(404);
  });
});
