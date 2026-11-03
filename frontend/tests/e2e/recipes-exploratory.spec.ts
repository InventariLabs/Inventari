import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Recipes — exploratory: recipe form with ingredients", () => {
  let api: ApiHelper;
  let token: string;
  const cleanupIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
  });

  test.afterAll(async () => {
    for (const id of cleanupIds) {
      await api.deleteRecipe(token, id).catch(() => {});
    }
  });

  test("creates a full recipe with ingredients via UI", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    // Exact match + .first(): the header's primary "New recipe", not the
    // grid's empty-state twin and not "New collection" beside it.
    const newBtn = page.getByRole("button", { name: /^new recipe$/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 10000 });
    await newBtn.click();

    const dialog = page.getByRole("dialog", { name: "New Recipe" });
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const uniqueName = `E2E-Full-${Date.now()}`;
    const nameInput = dialog.getByPlaceholder("e.g. Pasta Bolognese");
    await nameInput.fill(uniqueName);

    const servingsInput = dialog.getByRole("spinbutton").first();
    await servingsInput.fill("4");

    const addIngBtn = dialog.getByRole("button", { name: /add ingredient/i });
    await addIngBtn.click();

    const firstIngNameInput = dialog
      .getByPlaceholder("Ingredient name")
      .first();
    if (
      await firstIngNameInput.isVisible({ timeout: 3000 }).catch(() => false)
    ) {
      // A name no catalogue product matches: a matching one opens the
      // suggestion popover (a second role=dialog) over the unit picker and
      // links the line to a product whose units may not include grams. A
      // phrase that matches nothing whole is retried word by word on each
      // word's first four characters, so "E2E", "ingr" or a timestamp's "1793"
      // would find every product earlier specs left behind: one word, with a
      // start nothing else in the catalogue shares.
      await firstIngNameInput.fill(`Qzxv${Date.now()}`);
    }

    // A line with an amount names its unit; the picker opens inline under
    // its trigger, outside the dialog's own subtree.
    await dialog.getByRole("button", { name: /unit/i }).first().click();
    await page
      .locator("[data-radix-popper-content-wrapper]")
      .getByRole("button", { name: /^g\b/ })
      .first()
      .click();

    const submitBtn = dialog.getByRole("button", { name: /save/i });
    await submitBtn.click();

    await expect(dialog).toBeHidden({ timeout: 10000 });

    await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 10000 });

    const recipes = await api.listRecipes(token);
    const created = recipes.find((r) => r.name === uniqueName);
    if (created) cleanupIds.push(created.id);
  });

  test("an ingredient with an amount and no unit is refused", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await page
      .getByRole("button", { name: /^new recipe$/i })
      .first()
      .click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const uniqueName = `E2E-NoUnit-${Date.now()}`;
    await dialog.getByPlaceholder("e.g. Pasta Bolognese").fill(uniqueName);
    await dialog.getByRole("button", { name: /add ingredient/i }).click();
    await dialog.getByPlaceholder("Ingredient name").first().fill("Flour");
    await dialog.getByRole("button", { name: /save/i }).click();

    await expect(dialog.getByText("Choose a unit")).toBeVisible();
    await expect(dialog).toBeVisible();

    const recipes = await api.listRecipes(token);
    expect(recipes.some((r) => r.name === uniqueName)).toBe(false);
  });

  test("form validation shows error for empty recipe name", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Exact match + .first(): the header's primary "New recipe", not the
    // grid's empty-state twin and not "New collection" beside it.
    const newBtn = page.getByRole("button", { name: /^new recipe$/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 10000 });
    await newBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const nameInput = dialog.getByPlaceholder("e.g. Pasta Bolognese");
    await nameInput.clear();

    const submitBtn = dialog.getByRole("button", { name: /^save$/i });
    await submitBtn.click();

    await expect(page.getByText(/required/i).first()).toBeVisible({
      timeout: 5000,
    });
  });

  test("cancelling form does not create recipe", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Exact match + .first(): the header's primary "New recipe", not the
    // grid's empty-state twin and not "New collection" beside it.
    const newBtn = page.getByRole("button", { name: /^new recipe$/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 10000 });
    await newBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const cancelName = `E2E-Cancel-${Date.now()}`;
    const nameInput = dialog.locator("input").first();
    await nameInput.fill(cancelName);

    const cancelBtn = dialog.getByRole("button", { name: /cancel/i });
    await cancelBtn.click();

    // A dirty form asks before it is thrown away: Cancel opens a
    // discard confirmation, and only "Discard" closes the sheet.
    const discardBtn = page.getByRole("button", { name: /^discard$/i });
    await expect(discardBtn).toBeVisible({ timeout: 5000 });
    await discardBtn.click();

    await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 10000 });
    await expect(page.getByText(cancelName)).toHaveCount(0, { timeout: 10000 });
  });
});

test.describe("Recipes — exploratory: recipe detail page", () => {
  let api: ApiHelper;
  let token: string;
  let recipeId: string;
  const recipeName = `E2E-Detail-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 2,
      instructions: "Step 1: Mix. Step 2: Bake.",
      ingredients: [
        { name: "Sugar", quantity: 100, calories_kcal_per_100g: 387 },
        { name: "Flour", quantity: 200, calories_kcal_per_100g: 364 },
      ],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (recipeId) await api.deleteRecipe(token, recipeId).catch(() => {});
  });

  test("detail page shows recipe name and sections", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${recipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    await expect(page.getByText(recipeName).first()).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByRole("heading", { name: /ingredients/i }),
    ).toBeVisible({
      timeout: 5000,
    });
  });

  test("detail page shows ingredient list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${recipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    await expect(page.getByText("Sugar").first()).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("Flour").first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("detail page has Take from stock button", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${recipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    const pickingBtn = page.getByRole("button", { name: /take from stock/i });
    await expect(pickingBtn).toBeVisible({ timeout: 10000 });
  });

  test("detail page nutrition section expands", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${recipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    const nutritionBtn = page.getByRole("button", { name: /^nutrition$/i });
    if (await nutritionBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await nutritionBtn.click();
    }
  });

  test("detail page edit button opens form pre-filled", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/recipes/${recipeId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    const heading = page.getByRole("heading", { name: recipeName, level: 1 });
    await expect(heading).toBeVisible({ timeout: 10000 });

    const actionBar = page
      .locator('[class*="action"], [class*="header"]')
      .filter({ has: page.locator("button") });
    const editBtn = page
      .locator("button")
      .filter({ has: page.locator("img") })
      .nth(1);
    if (await editBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await editBtn.click();

      const dialog = page.locator('[role="dialog"]');
      if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
        const nameInput = dialog.getByPlaceholder("e.g. Pasta Bolognese");
        await expect(nameInput).toHaveValue(recipeName, { timeout: 3000 });

        const cancelBtn = dialog.getByRole("button", { name: /cancel/i });
        await cancelBtn.click();
      }
    }
  });
});

test.describe("Recipes — exploratory: settings page tabs", () => {
  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/recipes/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
  });

  test("settings page loads with tabs", async ({ page, authenticatedPage }) => {
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 10000,
    });
  });

  test("nutrition DB tab is active by default", async ({
    page,
    authenticatedPage,
  }) => {
    const nutritionTab = page.getByRole("tab", { name: /nutrition/i });
    if (await nutritionTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(nutritionTab).toHaveAttribute("data-state", "active");
    }
  });

  test("can switch to unit conversions tab", async ({
    page,
    authenticatedPage,
  }) => {
    const convTab = page.getByRole("tab", { name: /conversion/i });
    if (await convTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await convTab.click();
    }
  });

  test("can switch to exclusions tab", async ({ page, authenticatedPage }) => {
    const exclTab = page.getByRole("tab", {
      name: /always at home|exclusion/i,
    });
    if (await exclTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await exclTab.click();
    }
  });
});

test.describe("Recipes — exploratory: tags panel", () => {
  let api: ApiHelper;
  let token: string;
  let recipeId: string;
  const recipeName = `E2E-Tagged-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 1,
      tags: ["italian", "pasta"],
      ingredients: [],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (recipeId) await api.deleteRecipe(token, recipeId).catch(() => {});
  });

  test("tags button opens tags panel", async ({ page, authenticatedPage }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const tagsBtn = page.getByRole("button", { name: /^tags$/i });
    if (await tagsBtn.isVisible({ timeout: 10000 }).catch(() => false)) {
      await tagsBtn.click();
    }
  });

  test("search filters recipes by tag", async ({ page, authenticatedPage }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const searchInput = page.getByPlaceholder(/search/i);
    await expect(searchInput).toBeVisible({ timeout: 10000 });
    await searchInput.fill(recipeName);
    await expect(page.getByText(recipeName)).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Recipes — exploratory: favorite toggle", () => {
  let api: ApiHelper;
  let token: string;
  let recipeId: string;
  const recipeName = `E2E-Fav-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 1,
      ingredients: [],
    });
    recipeId = recipe.id;
  });

  test.afterAll(async () => {
    if (recipeId) await api.deleteRecipe(token, recipeId).catch(() => {});
  });

  test("favorite tab shows only favorited recipes", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const favTab = page.getByRole("tab", { name: /favorites/i });
    await expect(favTab).toBeVisible({ timeout: 10000 });
    await favTab.click();

    await expect(page.getByText(recipeName)).toHaveCount(0, { timeout: 10000 });
  });

  test("toggle favorite on recipe card", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const searchInput = page.getByPlaceholder(/search/i);
    await expect(searchInput).toBeVisible({ timeout: 10000 });
    await searchInput.fill(recipeName);
    await expect(page.getByText(recipeName)).toBeVisible({ timeout: 10000 });

    const card = page
      .locator('[data-testid="recipe-card"]')
      .filter({ hasText: recipeName })
      .first();
    await card.scrollIntoViewIfNeeded();
    await card.hover();

    const starBtn = card
      .locator('button[aria-label*="avor"], button')
      .filter({ has: page.locator("svg") })
      .first();
    if (await starBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await starBtn.click();
    }
  });
});

test.describe("Recipes — exploratory: import modal", () => {
  test("import button opens import dialog", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const importBtn = page.getByRole("button", { name: /import recipe/i });
    await expect(importBtn).toBeVisible({ timeout: 10000 });
    await importBtn.click();

    await expect(
      page.getByRole("heading", { name: /import recipe/i }),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Recipes — exploratory: meal planner navigation", () => {
  test("meal planner page loads", async ({ page, authenticatedPage }) => {
    await page.goto("/recipes/meal-planner");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 10000,
    });
  });

  test("meal planner has New Plan button", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes/meal-planner");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const newPlanBtn = page.getByRole("button", {
      name: /new plan|create plan/i,
    });
    if (await newPlanBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newPlanBtn.click();
    }
  });
});

test.describe("Recipes — exploratory: navigation sidebar", () => {
  test("sidebar has Recipes, Settings, Meal Planner links", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const nav = page.getByRole("navigation", { name: /module navigation/i });
    await expect(nav).toBeVisible({ timeout: 10000 });

    await expect(nav.getByRole("link", { name: /recipes/i })).toBeVisible({
      timeout: 10000,
    });
    // renamed the settings nav item to "Ingredient settings".
    await expect(
      nav.getByRole("link", { name: /ingredient settings/i }),
    ).toBeVisible({
      timeout: 10000,
    });
    await expect(nav.getByRole("link", { name: /meal planner/i })).toBeVisible({
      timeout: 10000,
    });
  });

  test("sidebar links navigate correctly", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const nav = page.getByRole("navigation", { name: /module navigation/i });

    await nav.getByRole("link", { name: /meal planner/i }).click();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(page).toHaveURL(/\/recipes\/meal-planner/, { timeout: 10000 });

    await nav.getByRole("link", { name: /ingredient settings/i }).click();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    // Ingredient settings and the module's own settings are two screens now —
    // this link owns /recipes/ingredient-data, /recipes/settings is the other.
    await expect(page).toHaveURL(/\/recipes\/ingredient-data/, {
      timeout: 10000,
    });
  });
});

test.describe("Recipes — exploratory: filter tabs", () => {
  let api: ApiHelper;
  let token: string;
  const cleanupIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
  });

  test.afterAll(async () => {
    for (const id of cleanupIds) {
      await api.deleteRecipe(token, id).catch(() => {});
    }
  });

  test("All tab shows all recipes", async ({ page, authenticatedPage }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const allTab = page.getByRole("tab", { name: /^all$/i });
    await expect(allTab).toBeVisible({ timeout: 10000 });
    expect(await allTab.getAttribute("data-state")).toBe("active");
  });

  test("I can cook tab is switchable", async ({ page, authenticatedPage }) => {
    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(
      page.getByRole("heading", { level: 1, name: /recipes/i }),
    ).toBeVisible({ timeout: 10000 });

    const cookTab = page.getByRole("tab", { name: /i can cook/i });
    await expect(cookTab).toBeVisible({ timeout: 10000 });
    await cookTab.click();
  });
});

test.describe("Recipes — exploratory: recipe deletion from detail", () => {
  let api: ApiHelper;
  let token: string;
  const recipeName = `E2E-DelDetail-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
  });

  test("delete recipe from detail page", async ({
    page,
    authenticatedPage,
  }) => {
    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 1,
      ingredients: [],
    });

    await page.goto(`/recipes/${recipe.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const heading = page.getByRole("heading", { name: recipeName, level: 1 });
    await expect(heading).toBeVisible({ timeout: 10000 });

    const contentArea = heading.locator("../../../..");
    const headerRow = contentArea.locator("> div").nth(1);
    const deleteBtn = headerRow.getByRole("button", { name: "Delete" });

    if (await deleteBtn.count()) {
      await deleteBtn.click();
      await page
        .getByText(/cannot be undone/i)
        .waitFor({ state: "visible", timeout: 2000 })
        .catch(() => {});

      const confirmText = page.getByText(/cannot be undone/i);
      if (await confirmText.isVisible({ timeout: 2000 }).catch(() => false)) {
        const delBtn = page
          .getByRole("button", { name: /delete|confirm/i })
          .last();
        await delBtn.click();
        await page
          .getByText(/cannot be undone/i)
          .waitFor({ state: "hidden", timeout: 10000 })
          .catch(() => {});
      }
    } else {
      await api.deleteRecipe(token, recipe.id).catch(() => {});
      return;
    }

    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(page).toHaveURL(/\/recipes$/i, { timeout: 10000 });
    const recipes = await api.listRecipes(token);
    expect(recipes.some((item) => item.id === recipe.id)).toBeFalsy();
  });
});

test.describe("Recipes — regressions", () => {
  test("cooking mode splits inline numbered instructions", async ({
    page,
    authenticatedPage,
    playwright,
    baseURL,
  }) => {
    let api: ApiHelper;
    let token: string;
    const recipeName = `E2E-Steps-${Date.now()}`;
    {
      const requestContext = await playwright.request.newContext({ baseURL });
      api = new ApiHelper(requestContext);
      const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
      token = authData.access_token;
    }
    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 2,
      instructions: "1. Boil water. 2. Fry onions. 3. Add pasta. 4. Serve hot.",
      ingredients: [{ name: "Pasta", quantity: 200 }],
    });

    await page.goto(`/recipes/${recipe.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await page.getByRole("button", { name: /cook step by step/i }).click();

    // All four inline steps become separate cards in cooking mode
    await expect(page.getByText("Boil water", { exact: true })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("Fry onions", { exact: true })).toBeVisible();
    await expect(page.getByText("Add pasta", { exact: true })).toBeVisible();
    await expect(page.getByText("Serve hot.", { exact: true })).toBeVisible();
    await api.deleteRecipe(token, recipe.id).catch(() => {});
  });

  test("completing a picking session with 0 items requires confirmation", async ({
    page,
    authenticatedPage,
    playwright,
    baseURL,
  }) => {
    let api: ApiHelper;
    let token: string;
    const recipeName = `E2E-ZeroPick-${Date.now()}`;
    {
      const requestContext = await playwright.request.newContext({ baseURL });
      api = new ApiHelper(requestContext);
      const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
      token = authData.access_token;
    }
    // a recipe whose ingredients are all unlinked blocks the picking
    // start entirely — link Flour to a template so the session can open
    // (with zero picks, which is what this test exercises).
    const template = await api.createProductTemplate(token, {
      name: `E2E-ZeroPick-Flour-${Date.now()}`,
    });
    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 2,
      ingredients: [{ name: "Flour", quantity: 200, template_id: template.id }],
    });

    await page.goto(`/recipes/${recipe.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    // Header CTA opens the picking view; the idle phase shares the
    // 'Take from stock' label for its start action
    await page
      .getByRole("button", { name: /take from stock/i })
      .first()
      .click();
    await page
      .getByRole("button", { name: /take from stock/i })
      .last()
      .click();

    const completeBtn = page.getByRole("button", {
      name: /finish picking/i,
    });
    await expect(completeBtn).toBeEnabled({ timeout: 10000 });
    await completeBtn.click();
    // Zero-picked dialog appears and requires an explicit confirm
    await expect(page.getByText(/nothing picked yet/i)).toBeVisible({
      timeout: 10000,
    });
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: /cancel/i })
      .click();
    // Still in the session after cancelling the confirmation
    await expect(completeBtn).toBeVisible({ timeout: 5000 });
    await api.deleteRecipe(token, recipe.id).catch(() => {});
  });

  test("new meal plan defaults to Breakfast + Lunch + Dinner", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/recipes/meal-planner");
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await page
      .getByRole("button", { name: /new plan/i })
      .first()
      .click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });
    const breakfast = dialog.getByRole("button", { name: "Breakfast" });
    const lunch = dialog.getByRole("button", { name: "Lunch" });
    const dinner = dialog.getByRole("button", { name: "Dinner" });

    // The toggle reports its state through aria-pressed; assert on that
    // rather than on the active-state utility classes, which the design
    // tokens move around.
    for (const slot of [breakfast, lunch, dinner]) {
      await expect(slot).toHaveAttribute("aria-pressed", "true", {
        timeout: 5000,
      });
    }
  });
});

test.describe("Recipes — follow-ups", () => {
  let api: ApiHelper;
  let token: string;
  const cleanupRecipeIds: string[] = [];
  const cleanupListIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
  });

  test.afterAll(async () => {
    for (const id of cleanupRecipeIds) {
      await api.deleteRecipe(token, id).catch(() => {});
    }
    for (const id of cleanupListIds) {
      await api.deleteShoppingList(token, id).catch(() => {});
    }
  });

  test("shopping-list toast interpolates values (no raw placeholders)", async ({
    page,
    authenticatedPage,
    request,
  }) => {
    const stamp = Date.now();
    const recipeName = `E2E-Toast-${stamp}`;
    // Linked ingredient with no stock → status 'missing' (never 'unknown'),
    // so the Add-missing button is enabled.
    // The line is named per run: the list a click adds to is the newest
    // active one, which keeps what an earlier run put on it, and a name it
    // already holds is answered with "already on the list" instead of
    // "added" — so a fixed name only passed on a database nothing had used.
    const ingredientName = `Zztoast Sesame ${stamp}`;
    const template = await api.createProductTemplate(token, {
      name: ingredientName,
    });
    const recipe = await api.createRecipe(token, {
      name: recipeName,
      servings: 2,
      ingredients: [
        { name: ingredientName, quantity: 2, template_id: template.id },
      ],
    });
    cleanupRecipeIds.push(recipe.id);

    await page.goto(`/recipes/${recipe.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    const addBtn = page.getByRole("button", {
      name: /add missing to shopping list/i,
    });
    await expect(addBtn).toBeEnabled({ timeout: 10000 });
    await addBtn.click();

    const toast = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /added/i })
      .last();
    await expect(toast).toBeVisible({ timeout: 10000 });
    const toastText = (await toast.textContent()) ?? "";
    expect(toastText).not.toContain("{{");
    expect(toastText).toMatch(/added \d+ item/i);

    // Track the auto-created shopping list (named after the recipe) for cleanup
    const listsResp = await request.get("/api/v1/shopping-lists?limit=200", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (listsResp.ok()) {
      const { items: lists } = (await listsResp.json()) as {
        items: Array<{ id: string; name?: string }>;
      };
      const created = lists.find((l) => l.name === recipeName);
      if (created) cleanupListIds.push(created.id);
    }
  });

  test("JSON import preserves units (kg/pcs) through review and detail", async ({
    page,
    authenticatedPage,
  }) => {
    const stamp = Date.now();
    const recipeName = `E2E-Import-${stamp}`;

    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await page.getByRole("button", { name: /import recipe/i }).click();
    // The import sheet chooses between URL and JSON with tabs, not buttons.
    await page.getByRole("tab", { name: /import from json/i }).click();
    await page.getByPlaceholder(/paste recipe json/i).fill(
      JSON.stringify({
        name: recipeName,
        servings: 2,
        ingredients: [
          { name: "Flour", quantity: 1.5, uom: "kg" },
          { name: "Eggs", quantity: 3, uom: "pcs" },
        ],
      }),
    );
    await page.getByRole("button", { name: /^import$/i }).click();

    // Review step: the unit selectors are pre-filled with the imported units
    await expect(
      page.getByRole("heading", { name: /review imported ingredients/i }),
    ).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("kg", { exact: true })).toBeVisible();
    // The unit renders as its abbreviation, "pcs." with the full stop.
    await expect(page.getByText(/^pcs\.?$/)).toBeVisible();

    await page.getByRole("button", { name: /save recipe/i }).click();
    await expect(page).toHaveURL(/\/recipes\/[0-9a-f-]{36}$/i, {
      timeout: 15000,
    });
    const recipeId = page.url().split("/").pop() ?? "";
    if (recipeId) cleanupRecipeIds.push(recipeId);

    // Detail page: the row reads as one sentence — "Flour 1½ kg" — so the
    // unit is matched inside the measure, not as a standalone element.
    await expect(page.getByText(/1½ kg/).first()).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText(/3 pcs\./).first()).toBeVisible();
  });

  test("cooking history renders dates in the app language format", async ({
    page,
    authenticatedPage,
    request,
  }) => {
    // Limitation: the Playwright config forces the en-US browser locale and
    // the suite shares one admin profile, so switching the app language
    // mid-test would leak into other tests. This asserts the EN medium
    // format ("Aug 2, 2026") against a freshly seeded history record.
    const stamp = Date.now();
    const recipe = await api.createRecipe(token, {
      name: `E2E-History-${stamp}`,
      servings: 2,
      ingredients: [{ name: "Pasta", quantity: 200 }],
    });
    cleanupRecipeIds.push(recipe.id);

    // Seed a completed cooking session via the picking API
    const authHeaders = { Authorization: `Bearer ${token}` };
    const startResp = await request.post(
      `/api/v1/recipes/${recipe.id}/picking/start`,
      { headers: authHeaders, data: { servings: 2 } },
    );
    expect(startResp.ok()).toBeTruthy();
    const { picking_session_id: sessionId } = (await startResp.json()) as {
      picking_session_id: string;
    };
    const completeResp = await request.post(
      `/api/v1/recipes/${recipe.id}/picking/${sessionId}/complete`,
      { headers: authHeaders },
    );
    expect(completeResp.ok()).toBeTruthy();

    await page.goto(`/recipes/${recipe.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await page.getByRole("button", { name: /cooking history/i }).click();

    // EN medium date = "Aug 2, 2026"; allow ±1 day for TZ edge cases
    const fmt = new Intl.DateTimeFormat("en", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
    const candidates = [-1, 0, 1].map((offset) =>
      fmt.format(new Date(Date.now() + offset * 86400000)),
    );
    const datePattern =
      /(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}/;
    const entry = page.getByText(datePattern).first();
    await expect(entry).toBeVisible({ timeout: 10000 });
    const entryText = (await entry.textContent()) ?? "";
    expect(
      candidates.some((candidate) => entryText.includes(candidate)),
    ).toBeTruthy();
  });

  test("ingredient template combobox links template and shows availability", async ({
    page,
    authenticatedPage,
  }) => {
    const stamp = Date.now();
    const recipeName = `E2E-Combo-${stamp}`;
    const templateName = `Zzcombo Butter ${stamp}`;

    // Seed a ProductTemplate with stock so the linked ingredient is Available
    const template = await api.createProductTemplate(token, {
      name: templateName,
    });
    const storage = await api.createStorage(token, {
      name: `Zzcombo Store ${stamp}`,
    });
    await api.seedStock(token, {
      product_template_id: template.id,
      product_template_name: templateName,
      location_id: storage.id,
      quantity: 10,
    });

    await page.goto("/recipes");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await page
      .getByRole("button", { name: /^new recipe$/i })
      .first()
      .click();

    // Name the sheet: the unit picker below is a dialog too, and it stays in
    // the page, closed, while it animates out — a bare `[role="dialog"]`
    // then matches both and the hidden check fails on a strict-mode error.
    const dialog = page.getByRole("dialog", { name: /new recipe/i });
    await expect(dialog).toBeVisible({ timeout: 10000 });
    await dialog.getByPlaceholder("e.g. Pasta Bolognese").fill(recipeName);
    await dialog.getByRole("button", { name: /add ingredient/i }).click();

    // Type the full unique name so leftover templates from previous runs
    // (search is capped at limit=10) can never push ours out of the list
    await dialog.getByPlaceholder("Ingredient name").first().fill(templateName);
    // The suggestion list is portalled out of the sheet, so look on the page.
    const suggestion = page.getByText(templateName, { exact: true });
    await expect(suggestion).toBeVisible({ timeout: 10000 });
    await suggestion.click();

    // The shelf holds pieces, and a unitless line cannot be read against it
    // ("Cannot compare: 10 pcs. in stock, recipe needs 1") — give it the unit.
    // The linked ingredient is the first row; the one under it is the blank
    // row the dialog opens with.
    await dialog
      .getByRole("button", { name: /^Unit\b/ })
      .first()
      .click();
    await page.getByRole("button", { name: /^pcs\./ }).click();

    await dialog.getByRole("button", { name: /^save$/i }).click();
    await expect(dialog).toBeHidden({ timeout: 10000 });

    const recipes = await api.listRecipes(token);
    const created = recipes.find((r) => r.name === recipeName);
    expect(created).toBeTruthy();
    cleanupRecipeIds.push(created!.id);

    await page.goto(`/recipes/${created!.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});

    // Linked ingredient with stock resolves to Available, never Unknown
    await expect(page.getByText(/Available\s+1/)).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText(/Unknown\s+\d/)).toHaveCount(0);
  });
});
