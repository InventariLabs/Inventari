import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Recipes — CRUD flow", () => {
  let api: ApiHelper;
  let token: string;
  let seedRecipeId: string;
  const seedName = `E2E-Recipe-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: seedName,
      servings: 2,
      ingredients: [],
    });
    seedRecipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token && seedRecipeId) {
      await api.deleteRecipe(token, seedRecipeId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("displays recipes page with heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes|przepisy/i }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("seeded recipe is visible in list", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByText(seedName)).toBeVisible({ timeout: 10000 });
  });

  test("searches recipes by name", async ({ page, authenticatedPage }) => {
    const searchInput = page.getByPlaceholder(/search|szukaj|wyszukaj|znajdź/i);
    await expect(searchInput).toBeVisible({ timeout: 10000 });

    await searchInput.fill("E2E-Recipe");
    await expect(page.getByText(seedName)).toBeVisible({ timeout: 10000 });
  });

  test("views recipe details (click to detail page)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.getByText(seedName).first().click();
    // The print-only card repeats the name in its own <h1>; a role query sees
    // only the heading that is actually shown on screen.
    await expect(
      page.getByRole("heading", { level: 1, name: seedName }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("creates a new recipe via UI", async ({ page, authenticatedPage }) => {
    let createdRecipeId: string | null = null;

    try {
      const uniqueName = `E2E-Recipe-UI-${Date.now()}`;
      // Name the button, not a loose /add|new|create/ race: "New collection"
      // sits next to "New recipe" in the header and used to win — the name
      // went into a collection and the recipe never existed. The grid's empty
      // state renders a second "New recipe", so take the header's own.
      const addButton = page
        .getByRole("button", { name: /^new recipe$/i })
        .first();
      await expect(addButton).toBeVisible({ timeout: 10000 });
      await addButton.click();

      const dialog = page.locator('[role="dialog"]');
      await expect(dialog).toBeVisible({ timeout: 10000 });

      const nameInput = dialog.locator("input").first();
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await nameInput.fill(uniqueName);

      const submitBtn = dialog.getByRole("button", {
        name: /save|create|submit|zapisz/i,
      });
      await submitBtn.click();

      await expect(dialog).toBeHidden({ timeout: 10000 });
      await page
        .waitForLoadState("networkidle", { timeout: 5000 })
        .catch(() => {});

      await expect(
        page.getByRole("heading", { name: uniqueName, level: 3 }),
      ).toBeVisible({ timeout: 10000 });

      const recipes = await api.listRecipes(token);
      const created = recipes.find(
        (r: { name: string }) => r.name === uniqueName,
      );
      if (created) createdRecipeId = created.id;
    } finally {
      if (createdRecipeId) {
        await api.deleteRecipe(token, createdRecipeId).catch(() => {});
      }
    }
  });

  test("deletes a recipe", async ({ page, authenticatedPage }) => {
    const deleteName = `E2E-Recipe-Del-${Date.now()}`;
    const toDelete = await api.createRecipe(token, {
      name: deleteName,
      servings: 1,
      ingredients: [],
    });

    // beforeEach loaded the list before this recipe existed; load it again.
    // A list or search that does not show the recipe must fail this case, not
    // end it early.
    await page.goto("/recipes");
    const searchInput = page.getByPlaceholder(/search|szukaj|wyszukaj|znajdź/i);
    await expect(searchInput).toBeVisible({ timeout: 10000 });
    await searchInput.fill(deleteName);

    const recipeRow = page
      .locator('[data-testid="recipe-card"]')
      .filter({ hasText: deleteName })
      .first();
    await expect(recipeRow).toBeVisible({ timeout: 10000 });
    await recipeRow.scrollIntoViewIfNeeded();
    await recipeRow.hover();

    const deleteBtn = recipeRow.locator('[data-testid="recipe-delete-btn"]');
    await expect(deleteBtn).toBeVisible({ timeout: 5000 });
    await deleteBtn.click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await dialog.getByRole("button", { name: /^(delete|usuń)$/i }).click();

    await expect(dialog).toBeHidden({ timeout: 10000 });
    await expect(page.getByText(deleteName)).toHaveCount(0, { timeout: 10000 });

    // Gone on the server too, not only hidden by the list.
    await expect(api.getRecipe(token, toDelete.id)).rejects.toThrow(
      /Failed to get recipe/,
    );
  });

  test("recipe card action buttons stay compact at 1280px", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });

    const card = page
      .locator('[data-testid="recipe-card"]')
      .filter({ hasText: seedName })
      .first();
    await expect(card).toBeVisible({ timeout: 10000 });
    await card.scrollIntoViewIfNeeded();
    await card.hover();

    const actionButtons = [
      card.getByRole("button", { name: "Edit", exact: true }),
      card.locator('[data-testid="recipe-duplicate-btn"]'),
      card.locator('[data-testid="recipe-delete-btn"]'),
    ];

    for (const button of actionButtons) {
      await expect(button).toBeAttached();
      const size = await button.evaluate((el) => ({
        width: el.clientWidth,
        height: el.clientHeight,
      }));
      expect(size.width).toBeLessThanOrEqual(32);
      expect(size.height).toBeLessThanOrEqual(32);
    }
  });
});

test.describe("Recipes — nutrition & conversions", () => {
  let api: ApiHelper;
  let token: string;
  let seededTagRecipeId: string | null = null;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    // The header shows the Tags button only while at least one tag exists
    // (over zero tags it opens onto an empty manager, so the tool is
    // hidden). Pin a tag down — otherwise the assertion depends on what
    // parallel specs happened to leave behind in the shared org.
    const stamp = Date.now();
    const recipe = await api.createRecipe(token, {
      name: `E2E-Nutrition-TagSeed-${stamp}`,
      servings: 2,
    });
    seededTagRecipeId = recipe.id;
    await ctx.post("/api/v1/recipes/bulk-tag", {
      headers: { Authorization: `Bearer ${token}` },
      data: { recipe_ids: [recipe.id], tags: [`E2E-Tag-${stamp}`] },
    });
  });

  test.afterAll(async () => {
    if (token && seededTagRecipeId) {
      await api.deleteRecipe(token, seededTagRecipeId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("navigates to Settings page with Ingredient Defaults tab", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 10000,
    });
  });

  test("navigates to Settings page with Unit Conversions tab", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 10000,
    });
  });

  test("Tags button is visible", async ({ page, authenticatedPage }) => {
    // Exact name: the tag filter row also renders a "Show all tags" button,
    // which /tags/i would match too (strict-mode violation).
    await expect(
      page.getByRole("button", { name: "Tags", exact: true }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("New recipe button opens form", async ({ page, authenticatedPage }) => {
    const newBtn = page.getByRole("button", { name: /^new recipe$/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 10000 });
    await newBtn.click();
    await page
      .locator('[role="dialog"]')
      .or(page.getByRole("heading", { name: /new recipe|create/i }))
      .first()
      .waitFor({ state: "visible", timeout: 5000 })
      .catch(() => {});
    const hasDialog = await page
      .locator('[role="dialog"]')
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    const hasHeading = await page
      .getByRole("heading", { name: /new recipe|create/i })
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    expect(hasDialog || hasHeading).toBeTruthy();
  });
});

test.describe("Recipes — detail & sub-pages", () => {
  let api: ApiHelper;
  let token: string;
  let detailRecipeId: string;
  const detailRecipeName = `E2E-Detail-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: detailRecipeName,
      servings: 2,
      ingredients: [],
    });
    detailRecipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token && detailRecipeId) {
      await api.deleteRecipe(token, detailRecipeId).catch(() => {});
    }
  });

  test("recipe detail page loads (seeded)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Open this describe's own recipe by name. Taking whichever card is first
    // lets a parallel worker's cleanup delete the clicked recipe mid-navigation.
    await page
      .getByPlaceholder(/search/i)
      .first()
      .fill(detailRecipeName);
    const card = page
      .locator('[data-testid="recipe-card"]')
      .filter({ hasText: detailRecipeName })
      .first();
    await expect(card).toBeVisible({ timeout: 15000 });

    const loaded = expectApiOk(
      page,
      new RegExp(`/api/v1/recipes/${detailRecipeId}(\\?|$)`),
    );
    await card.click();
    await loaded;

    await expect(page).toHaveURL(new RegExp(`/recipes/${detailRecipeId}$`));
    await expect(
      page.getByRole("heading", { level: 1, name: detailRecipeName }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("settings page loads via ingredient-defaults tab", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes/settings");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 15000,
    });
  });

  test("settings page loads with conversions tab", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes/settings");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 15000,
    });
  });
});

test.describe("Recipes — tags & unit conversions (API)", () => {
  let api: ApiHelper;
  let token: string;
  let recipeWithTagId: string;
  let conversionId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: `E2E-TagRecipe-${Date.now()}`,
      servings: 1,
      tags: ["e2e-test-tag"],
      ingredients: [],
    });
    recipeWithTagId = recipe.id;
  });

  test.afterAll(async () => {
    if (token) {
      if (recipeWithTagId)
        await api.deleteRecipe(token, recipeWithTagId).catch(() => {});
      if (conversionId)
        await api.deleteUnitConversion(token, conversionId).catch(() => {});
    }
  });

  test("GET /recipes/tags returns seeded tag", async () => {
    const tags = await api.listTags(token);
    const found = tags.find((t) => t.name === "e2e-test-tag");
    expect(found).toBeTruthy();
    expect(found!.count).toBeGreaterThanOrEqual(1);
  });

  test("PATCH /recipes/tags/{name}/color sets a color", async () => {
    const result = await api.setTagColor(token, "e2e-test-tag", "#ff5733");
    expect(result.color).toBe("#ff5733");
  });

  test("POST /recipes/unit-conversions creates a conversion", async () => {
    const conv = await api.createUnitConversion(token, {
      ingredient_key: "flour",
      ingredient_name: "Flour",
      source_unit: "cup",
      metric_quantity: 120,
      metric_unit: "g",
      category: "baking",
    });
    conversionId = conv.id;
    expect(conv.id).toBeTruthy();
  });

  test("GET /recipes/unit-conversions lists the created conversion", async () => {
    const conv = await api.createUnitConversion(token, {
      ingredient_key: "sugar",
      ingredient_name: "Sugar",
      source_unit: "cup",
      metric_quantity: 200,
      metric_unit: "g",
      category: "baking",
    });
    const conversions = await api.listUnitConversions(token);
    const found = conversions.find(
      (c: Record<string, unknown>) => c.id === conv.id,
    );
    expect(found).toBeTruthy();
    await api.deleteUnitConversion(token, conv.id).catch(() => {});
  });
});

test.describe("Recipes — availability (API)", () => {
  let api: ApiHelper;
  let token: string;
  let recipeId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: `E2E-AvailRecipe-${Date.now()}`,
      servings: 2,
      ingredients: [{ name: "Test Ingredient", quantity: 100, unit: "g" }],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token && recipeId)
      await api.deleteRecipe(token, recipeId).catch(() => {});
  });

  test("GET /recipes/{id}/availability returns match data", async () => {
    const avail = await api.getRecipeAvailability(token, recipeId, 2);
    expect(avail.match_percentage).toBeDefined();
    expect(avail.ingredients).toBeDefined();
    expect(Array.isArray(avail.ingredients)).toBe(true);
  });

  test("GET /recipes/available returns list of cookable recipes", async () => {
    const available = await api.getAvailableRecipes(token);
    expect(Array.isArray(available)).toBe(true);
  });
});

test.describe("Recipes — picking flow (API)", () => {
  test.describe.configure({ mode: "serial" });
  let api: ApiHelper;
  let token: string;
  let recipeId: string;
  let pickingSessionId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: `E2E-PickRecipe-${Date.now()}`,
      servings: 2,
      ingredients: [{ name: "Pickable Item", quantity: 2, unit: "pcs" }],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token && recipeId) {
      if (pickingSessionId)
        await api
          .cancelPicking(token, recipeId, pickingSessionId)
          .catch(() => {});
      await api.deleteRecipe(token, recipeId).catch(() => {});
    }
  });

  test("POST /recipes/{id}/picking/start starts a session", async () => {
    const session = await api.startPicking(token, recipeId, 2);
    expect(session.picking_session_id).toBeTruthy();
    expect(session.recipe_name).toBeTruthy();
    expect(session.items_to_pick).toBeDefined();
    expect(Array.isArray(session.items_to_pick)).toBe(true);
    pickingSessionId = session.picking_session_id as string;
  });

  test("POST /recipes/{id}/picking/{sid}/scan scans an item", async () => {
    expect(pickingSessionId).toBeTruthy();
    const scan = await api.scanPicking(token, recipeId, pickingSessionId, {
      barcode: "SCAN-E2E-TEST",
    });
    expect(scan.status).toBeTruthy();
  });

  test("POST /recipes/{id}/picking/{sid}/complete ends session", async () => {
    expect(pickingSessionId).toBeTruthy();
    await api.completePicking(token, recipeId, pickingSessionId);
    pickingSessionId = "";
  });

  test("GET /recipes/{id}/history returns cooking history", async () => {
    const history = await api.getRecipeHistory(token, recipeId);
    expect(Array.isArray(history)).toBe(true);
  });
});

test.describe("Recipes — meal planner (API)", () => {
  test.describe.configure({ mode: "serial" });
  let api: ApiHelper;
  let token: string;
  let recipeId: string;
  let planId: string;
  let entryId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: `E2E-MealRecipe-${Date.now()}`,
      servings: 1,
      ingredients: [],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token) {
      if (planId) await api.deleteMealPlan(token, planId).catch(() => {});
      if (recipeId) await api.deleteRecipe(token, recipeId).catch(() => {});
    }
  });

  test("POST /meal-plans creates a plan", async () => {
    const today = new Date().toISOString().split("T")[0];
    const nextWeek = new Date(Date.now() + 7 * 86400000)
      .toISOString()
      .split("T")[0];
    const plan = await api.createMealPlan(token, {
      name: `E2E-MealPlan-${Date.now()}`,
      start_date: today,
      end_date: nextWeek,
      enabled_slots: ["LUNCH"],
    });
    planId = plan.id;
    expect(plan.id).toBeTruthy();
  });

  test("POST /meal-plans/{id}/entries adds an entry", async () => {
    if (!planId) return;
    const today = new Date().toISOString().split("T")[0];
    const entry = await api.addMealPlanEntry(token, planId, {
      date: today,
      slot: "LUNCH",
      recipe_id: recipeId,
    });
    entryId = entry.id;
    expect(entry.id).toBeTruthy();
  });

  test("GET /meal-plans lists created plan", async () => {
    const plans = await api.listMealPlans(token);
    const found = plans.find((p) => p.id === planId);
    expect(found).toBeTruthy();
    expect(found!.entry_count).toBeGreaterThanOrEqual(1);
  });

  test("GET /meal-plans/suggestions returns suggestions", async () => {
    const today = new Date().toISOString().split("T")[0];
    const suggestions = await api.getMealPlanSuggestions(token, today, "LUNCH");
    expect(Array.isArray(suggestions)).toBe(true);
  });
});

test.describe("Recipes — ingredient row on mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  let api: ApiHelper;
  let token: string;
  let recipeId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    // No template_id and no group_name → availability status "unknown",
    // the only state that renders the link-to-product button.
    const recipe = await api.createRecipe(token, {
      name: `E2E-RecipeMobile-${Date.now()}`,
      servings: 1,
      ingredients: [
        {
          name: "Fresh spinach",
          quantity: 100,
          template_id: null,
          ingredient_group_name: null,
        },
      ],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token && recipeId) {
      await api.deleteRecipe(token, recipeId).catch(() => {});
    }
  });

  test("ingredient name keeps non-zero width and does not overlap the link button at 390px", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${recipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const nameContainer = page.getByTestId("ingredient-name").first();
    await expect(nameContainer).toBeVisible({ timeout: 10000 });
    const nameBox = await nameContainer.boundingBox();
    expect(nameBox).not.toBeNull();
    expect(nameBox!.width).toBeGreaterThan(0);

    const linkButton = page.getByRole("button", {
      name: /link to product|powiąż z produktem/i,
    });
    await expect(linkButton).toBeVisible({ timeout: 10000 });
    const buttonBox = await linkButton.boundingBox();
    expect(buttonBox).not.toBeNull();

    // The name box must end before the button starts — no horizontal overlap.
    expect(nameBox!.x + nameBox!.width).toBeLessThanOrEqual(buttonBox!.x + 1);

    // Below sm the button is icon-only: its text label must be hidden.
    await expect(linkButton.locator("span")).toBeHidden();
  });
});

test.describe("Recipes — detail layout at intermediate widths", () => {
  let api: ApiHelper;
  let token: string;
  let recipeId: string;
  // Short enough to fit the title block's 20rem floor at 1100px, long enough
  // to have wrapped when the action bar still crushed the title to ~150px.
  const recipeName = `Spaghetti Carbonara ${Math.random()
    .toString(36)
    .substring(2, 7)}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    // No template_id / ingredient_group_name → availability status "unknown",
    // which renders the "link to product" action next to every ingredient name.
    // That action is what used to clip ingredient names on a half-width window.
    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 2,
      ingredients: [
        {
          name: "Spaghetti pasta",
          quantity: 400,
          template_id: null,
          ingredient_group_name: null,
        },
        {
          name: "Guanciale",
          quantity: 150,
          template_id: null,
          ingredient_group_name: null,
        },
        {
          name: "Pecorino Romano cheese",
          quantity: 100,
          template_id: null,
          ingredient_group_name: null,
        },
        {
          name: "Free-range egg yolks",
          quantity: 4,
          template_id: null,
          ingredient_group_name: null,
        },
        {
          name: "Freshly ground black pepper",
          quantity: 2,
          template_id: null,
          ingredient_group_name: null,
        },
      ],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (token && recipeId) {
      await api.deleteRecipe(token, recipeId).catch(() => {});
    }
  });

  for (const viewport of [
    { width: 1100, height: 800 },
    { width: 1280, height: 800 },
  ]) {
    test(`ingredient names are not clipped and the title stays on one line at ${viewport.width}px`, async ({
      page,
      authenticatedPage,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto(`/recipes/${recipeId}`);
      await page
        .waitForLoadState("networkidle", { timeout: 15000 })
        .catch(() => {});

      const heading = page.getByRole("heading", { level: 1 }).first();
      await expect(heading).toBeVisible({ timeout: 15000 });
      await expect(heading).toHaveText(recipeName);

      // The title must not be crushed into a multi-line block: its height
      // stays within 1.5× its line-height (one line).
      const titleMetrics = await heading.evaluate((el) => {
        const cs = window.getComputedStyle(el);
        const fontSize = parseFloat(cs.fontSize) || 16;
        const lineHeight = parseFloat(cs.lineHeight) || fontSize * 1.2;
        return { height: el.getBoundingClientRect().height, lineHeight };
      });
      expect(titleMetrics.height).toBeLessThanOrEqual(
        titleMetrics.lineHeight * 1.5,
      );

      // Every ingredient name is un-clipped: no horizontal overflow.
      const names = page.getByTestId("ingredient-name");
      const count = await names.count();
      expect(count).toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        const name = names.nth(i);
        await expect(name).toBeVisible({ timeout: 10000 });
        const overflow = await name.evaluate((el) => ({
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
        }));
        expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
      }
    });
  }
});
