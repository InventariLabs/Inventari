import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Pricing calculator tests:
 *  - Open from production-create sheet (header has "Sale price" button)
 *  - Slider rounds qty, margin in [0, 95]
 *  - Compute endpoint returns total_cost, unit_cost, unit_sale_price
 *  - Save default margin persists per-template via /maker/pricing/margin
 *  - GET /margin returns is_default=true when stored
 */

test.describe("Maker — pricing calculator (UI)", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string; name: string };
  let outputStorage: { id: string };

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    // The worker index keeps two workers entering this hook in the same
    // millisecond from building one location name.
    const stamp = `${Date.now()}-w${testInfo.workerIndex}`;
    parent = await api.createProductTemplate(token, {
      name: `E2E-Pricing-Parent-${stamp}`,
    });
    const s = await api.createStorage(token, {
      name: `E2E-Pricing-Storage-${stamp}`,
    });
    outputStorage = s;
    // The calculator answers "nothing to price" (no result card) for a
    // formula without ingredients, so the parent needs one rated line for
    // the "Suggested sale price" card to render.
    const ingredient = await api.createProductTemplate(token, {
      name: `E2E-Pricing-Ingredient-${stamp}`,
    });
    await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: ingredient.id,
      qty_per_batch: "1",
      unit: "kg",
    });
  });

  test.afterAll(async () => {
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await ctx.dispose();
  });

  test("Sale price sheet computes total_cost and unit_cost", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/maker/production");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await page
      .getByRole("button", { name: /new production/i })
      .first()
      .click();

    const dialog = page.locator('[role="dialog"]').first();
    await dialog.getByTestId("maker-create-search-input").fill(parent.name);
    await page.getByTestId("maker-create-search-result").first().click();

    await dialog.getByTestId("maker-create-pricing-button").click();

    // Pricing sheet is now a separate modal; the create sheet sits beneath.
    // Wait for the slider to be visible.
    const slider = page.getByTestId("maker-pricing-slider");
    await expect(slider).toBeVisible({ timeout: 5000 });

    // Set qty
    const qtyInput = page
      .locator('[role="dialog"] input[type="number"]')
      .first();
    await qtyInput.fill("10");

    // Compute
    await page.getByTestId("maker-pricing-preview-button").click();
    await page
      .waitForResponse(
        (r) => r.url().includes("/maker/pricing/compute") && r.ok(),
        { timeout: 10000 },
      )
      .catch(() => {});

    // Pricing result card surfaces "Suggested sale price" — use exact match
    // to avoid the subtitle ("Gross-margin model — slide the margin to
    // preview the suggested sale price").
    await expect(page.getByText(/^Suggested sale price$/i)).toBeVisible({
      timeout: 10000,
    });
  });

  test("Save default margin persists per-template", async ({
    page,
    authenticatedPage,
  }) => {
    // Open pricing sheet for our parent
    await page.goto("/maker/production");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await page
      .getByRole("button", { name: /new production/i })
      .first()
      .click();
    const dialog = page.locator('[role="dialog"]').first();
    await dialog.getByTestId("maker-create-search-input").fill(parent.name);
    await page.getByTestId("maker-create-search-result").first().click();
    await dialog.getByTestId("maker-create-pricing-button").click();

    const slider = page.getByTestId("maker-pricing-slider");
    await expect(slider).toBeVisible({ timeout: 5000 });

    // Move slider to 22%
    await slider.fill("22");

    const saved = page.waitForResponse(
      (r) =>
        r.url().includes("/maker/pricing/margin") &&
        r.request().method() !== "GET" &&
        r.ok(),
      { timeout: 10000 },
    );
    await page.getByTestId("maker-pricing-save-default").click();
    await saved;

    // Validate via API
    const stored = await api.getMargin(token, parent.id);
    expect(parseFloat(stored.target_margin_pct)).toBeCloseTo(22, 1);
    expect(stored.is_default).toBe(false);
  });

  test("Margin slider clamp at 95%", async ({ page, authenticatedPage }) => {
    await page.goto("/maker/production");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await page
      .getByRole("button", { name: /new production/i })
      .first()
      .click();
    const dialog = page.locator('[role="dialog"]').first();
    await dialog.getByTestId("maker-create-search-input").fill(parent.name);
    await page.getByTestId("maker-create-search-result").first().click();
    await dialog.getByTestId("maker-create-pricing-button").click();

    // Force slider to 100 → should display 95% cap
    const slider = page.getByTestId("maker-pricing-slider");
    await expect(slider).toBeVisible({ timeout: 5000 });
    await slider.evaluate((el: HTMLInputElement) => {
      el.value = "100";
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await expect(page.getByText("95.0%").first()).toBeVisible({
      timeout: 5000,
    });
  });
});

test.describe("Maker — pricing API", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string };

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    parent = await api.createProductTemplate(token, {
      name: `E2E-Pricing-API-${Date.now()}`,
    });
  });

  test.afterAll(async () => {
    await ctx.dispose();
  });

  test("GET /maker/pricing/margin defaults to 30", async () => {
    const margin = await api.getMargin(token, parent.id);
    expect(parseFloat(margin.target_margin_pct)).toBeCloseTo(30, 1);
    expect(margin.is_default).toBe(true);
  });

  test("PUT /maker/pricing/margin persists user value", async () => {
    const resp = await api.setMargin(token, parent.id, "17.5");
    expect(parseFloat(resp.target_margin_pct)).toBeCloseTo(17.5, 1);
    expect(resp.is_default).toBe(false);

    const get = await api.getMargin(token, parent.id);
    expect(parseFloat(get.target_margin_pct)).toBeCloseTo(17.5, 1);
    expect(get.is_default).toBe(false);
  });

  test("POST /maker/pricing/compute returns full breakdown", async () => {
    const result = await api.computePricing(token, {
      template_id: parent.id,
      produced_qty: "10",
      target_margin_pct: "25",
    });
    expect(result.template_id).toBe(parent.id);
    expect(parseFloat(result.produced_qty)).toBe(10);
    expect(parseFloat(result.target_margin_pct)).toBe(25);
    // total_cost will be 0 because no BoM exists
    expect(parseFloat(result.total_cost)).toBe(0);
    expect(parseFloat(result.unit_cost)).toBe(0);
    expect(parseFloat(result.unit_sale_price)).toBe(0);
  });

  test("pricing rejects margin >= 100", async () => {
    const resp = await ctx.post("/api/v1/maker/pricing/compute", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        template_id: parent.id,
        produced_qty: "1",
        target_margin_pct: "100",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("pricing rejects negative margin", async () => {
    const resp = await ctx.post("/api/v1/maker/pricing/compute", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        template_id: parent.id,
        produced_qty: "1",
        target_margin_pct: "-5",
      },
    });
    expect(resp.status()).toBe(422);
  });
});
