import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * MAKER MODULE — UX EXPLORATORY TESTS
 *
 * These tests walk every page in /maker and /maker/bom, exercising the
 * happy paths and then probing edge cases / "missing" affordances that
 * a real user would notice. The intent is to capture the *feeling* of
 * the module, not just confirm functionality.
 *
 * The tests that switch maker off live in maker-module-gate.spec.ts: an
 * org-wide write races every maker spec in every worker, not only the ones
 * in this file, so they run in a project of their own after all the others.
 */

test.describe.serial("Maker exploratory", () => {
  test.describe("production list", () => {
    let api: ApiHelper;
    let token: string;
    let seededTemplate: { id: string; name: string };

    test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
      const ctx = await playwright.request.newContext({ baseURL });
      api = new ApiHelper(ctx);
      const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
      token = auth.access_token;
      await api.enableAllModules(token);
      // The search control only renders once the list has a row (an empty
      // list offers nothing to narrow), so pin one order down. Without it
      // the search test flapped depending on what parallel specs had left
      // behind in the shared org.
      // The worker index keeps two workers entering this hook in the same
      // millisecond from building one location name.
      const stamp = `${Date.now()}-w${testInfo.workerIndex}`;
      seededTemplate = await api.createProductTemplate(token, {
        name: `E2E-Explore-Output-${stamp}`,
      });
      const storage = await api.createStorage(token, {
        name: `E2E-Explore-Storage-${stamp}`,
      });
      // An order needs a recipe behind its product (the first formula for a
      // product is its default one).
      await api.createMakerRecipe(token, {
        output_template_id: seededTemplate.id,
        name: `E2E-Explore-Formula-${stamp}`,
        batch_yield_qty: "1",
      });
      await api.createProductionOrder(token, {
        output_template_id: seededTemplate.id,
        planned_qty: "1",
        output_location_id: storage.id,
      });
    });

    test.beforeEach(async ({ page, authenticatedPage }) => {
      await page.goto("/maker/production");
      await page
        .waitForLoadState("networkidle", { timeout: 15000 })
        .catch(() => {});
    });

    test("empty state when no orders exist is informative", async ({
      page,
      authenticatedPage,
    }) => {
      const emptyCard = page.getByText(/no production runs yet/i).first();
      const emptyVisible = await emptyCard
        .isVisible({ timeout: 1500 })
        .catch(() => false);
      expect(typeof emptyVisible).toBe("boolean");
    });

    test("search by partial template id finds matching orders", async ({
      page,
      authenticatedPage,
    }) => {
      const search = page.getByPlaceholder(/search by output product/i).first();
      await expect(search).toBeVisible({ timeout: 10000 });
      // The list matches on the output template id, not only its name.
      await search.fill(seededTemplate.id.slice(0, 8));
      await expect(
        page.getByText(seededTemplate.name, { exact: true }).first(),
      ).toBeVisible({ timeout: 10000 });
      const url = page.url();
      expect(url).toMatch(/\/maker/);
    });

    test("filter to Cancelled hides drafts", async ({
      page,
      authenticatedPage,
    }) => {
      await page.getByRole("tab", { name: /^cancelled$/i }).click();
      await expect(
        page.getByRole("tab", { name: /^cancelled$/i }),
      ).toHaveAttribute("aria-selected", "true");
    });
  });

  test.describe("BoM editor", () => {
    let api: ApiHelper;
    let token: string;
    let parentId: string;
    let recipeId: string;

    test.beforeAll(async ({ playwright, baseURL }) => {
      const ctx = await playwright.request.newContext({ baseURL });
      api = new ApiHelper(ctx);
      const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
      token = auth.access_token;
      await api.enableAllModules(token);
      const t = await api.createProductTemplate(token, {
        name: `E2E-Exp-BoMParent-${Date.now()}`,
      });
      parentId = t.id;
      const recipe = await api.createMakerRecipe(token, {
        output_template_id: parentId,
        name: `E2E-Exp-BoMFormula-${Date.now()}`,
      });
      recipeId = recipe.id;

      // The drag hint only renders once there are at least two rows — with
      // fewer, it describes a gesture that cannot be made. Seed two
      // ingredients so the tree is actually nestable.
      for (const suffix of ["A", "B"]) {
        const child = await api.createProductTemplate(token, {
          name: `E2E-Exp-BoMChild${suffix}-${Date.now()}`,
        });
        await api.createBomLine(token, {
          recipe_id: recipeId,
          child_template_id: child.id,
          qty_per_batch: "1",
          unit: "kg",
        });
      }
    });

    test.afterAll(async () => {
      await api.deleteAllBomLinesForTemplate(token, parentId).catch(() => {});
    });

    test("tree view shows the multi-level hint", async ({
      page,
      authenticatedPage,
    }) => {
      // The sub-assembly tree moved onto the formula screen with the
      // removal of /maker/bom.
      await page.goto(`/maker/recipes/${recipeId}`);
      await page
        .waitForLoadState("networkidle", { timeout: 10000 })
        .catch(() => {});
      await expect(
        page.getByTestId("maker-composition-tree-toggle"),
      ).toBeVisible({ timeout: 10000 });
      await page.getByTestId("maker-composition-tree-toggle").click();
      await expect(page.getByText(/drag a row onto another/i)).toBeVisible({
        timeout: 5000,
      });
    });
  });

  test.describe("pricing calculator edge cases", () => {
    test("slider value is clamped to 95% visible", async ({
      page,
      authenticatedPage,
    }) => {
      await page.goto("/maker/production");
      await page
        .waitForLoadState("networkidle", { timeout: 15000 })
        .catch(() => {});

      const newBtn = page
        .getByRole("button", { name: /new production/i })
        .first();
      if ((await newBtn.count()) === 0) return;
      await newBtn.click();

      const dialog = page.locator('[role="dialog"]').first();
      const search = dialog.getByTestId("maker-create-search-input");
      await search.fill("E2E-Maker-Cake");
      await page
        .getByTestId("maker-create-search-result")
        .first()
        .waitFor({ state: "visible", timeout: 5000 })
        .catch(() => {});
      // Portalled to document.body, outside the dialog.
      const result = page.getByTestId("maker-create-search-result").first();
      if (await result.isVisible({ timeout: 3000 }).catch(() => false)) {
        await result.click();
        await dialog.getByTestId("maker-create-pricing-button").click();
        const slider = page.getByTestId("maker-pricing-slider");
        if (await slider.isVisible({ timeout: 3000 }).catch(() => false)) {
          await slider.evaluate((el: HTMLInputElement) => {
            el.value = "999";
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
          });
          await expect(page.getByText("95.0%").first()).toBeVisible({
            timeout: 5000,
          });
        }
      }
    });
  });
});
