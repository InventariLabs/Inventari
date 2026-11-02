import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * MAKER MODULE — BUG HUNT
 *
 * Aggressive probes that have surfaced real defects in past Inventari
 * modules.  Each test exercises an edge case that the happy-path spec
 * (maker.spec.ts) cannot reach.
 *
 * Findings that surface as failures are real bugs; reproduce them, open
 * an issue against the maker module, do not paper over them here.
 */

test.describe("Maker — bug hunt: input validation", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string };
  let child: { id: string };
  let recipeId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    parent = await api.createProductTemplate(token, {
      name: `E2E-BugHunt-Parent-${Date.now()}`,
    });
    child = await api.createProductTemplate(token, {
      name: `E2E-BugHunt-Child-${Date.now()}`,
    });
    // Lines are posted per formula now; the product-level POST /maker/bom
    // that took `parent_template_id` is gone.
    recipeId = await api.resolveDefaultRecipeId(token, parent.id);
  });

  test.afterAll(async () => {
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    await ctx.dispose();
  });

  test("BoM yield_loss_pct = -1 is rejected (cannot be negative)", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: child.id,
        qty_per_batch: "1",
        unit: "kg",
        yield_loss_pct: "-1",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("BoM yield_loss_pct = 100.01 is rejected (must be ≤ 100)", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: child.id,
        qty_per_batch: "1",
        unit: "kg",
        yield_loss_pct: "100.01",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("BoM qty_per_batch above MAX_DIGITS rejected", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: child.id,
        qty_per_batch: "12345678901.000", // > 12 digits before decimal
        unit: "kg",
      },
    });
    // Pydantic max_digits=12 ⇒ 422
    expect(resp.status()).toBe(422);
  });

  test("BoM unit > 8 chars is rejected", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: child.id,
        qty_per_batch: "1",
        unit: "kilograms", // 9 chars
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("notes > 500 chars is rejected", async () => {
    const resp = await ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        child_template_id: child.id,
        qty_per_batch: "1",
        unit: "kg",
        notes: "x".repeat(501),
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("planned_qty = 0 in production order is rejected", async () => {
    const storages = await api.listStorages(token);
    const resp = await ctx.post("/api/v1/maker/production/orders", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        output_template_id: parent.id,
        planned_qty: "0",
        output_location_id: storages[0].id,
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("notes > 500 chars in production order is rejected", async () => {
    const storages = await api.listStorages(token);
    const resp = await ctx.post("/api/v1/maker/production/orders", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        output_template_id: parent.id,
        planned_qty: "1",
        output_location_id: storages[0].id,
        notes: "x".repeat(501),
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("malformed UUID in path returns 422 (not 500)", async () => {
    const resp = await ctx.get("/api/v1/maker/production/orders/not-a-uuid", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect([400, 422]).toContain(resp.status());
  });
});

test.describe("Maker — bug hunt: pricing edge cases", () => {
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
      name: `E2E-BugHunt-Pricing-${Date.now()}`,
    });
  });

  test.afterAll(async () => {
    await ctx.dispose();
  });

  test("zero produced_qty rejected", async () => {
    const resp = await ctx.post("/api/v1/maker/pricing/compute", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        template_id: parent.id,
        produced_qty: "0",
        target_margin_pct: "30",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("negative produced_qty rejected", async () => {
    const resp = await ctx.post("/api/v1/maker/pricing/compute", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        template_id: parent.id,
        produced_qty: "-5",
        target_margin_pct: "30",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("setMargin accepts margin=0 (no markup)", async () => {
    const r = await api.setMargin(token, parent.id, "0");
    expect(parseFloat(r.target_margin_pct)).toBe(0);
  });

  test("setMargin rejects margin=100 (must be < 100)", async () => {
    const resp = await ctx.put(`/api/v1/maker/pricing/margin/${parent.id}`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { target_margin_pct: "100" },
    });
    expect(resp.status()).toBe(422);
  });

  test("pricing non-existent template returns 400 with descriptive error", async () => {
    // Today the service raises ValueError when the template is missing,
    // and the router maps that to 400 (not 404). Acceptable but worth
    // noting: a true 404 would be more RESTful here.
    const resp = await ctx.post("/api/v1/maker/pricing/compute", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        template_id: "00000000-0000-0000-0000-000000000000",
        produced_qty: "1",
        target_margin_pct: "30",
      },
    });
    expect([400, 404]).toContain(resp.status());
    // Error body should describe which template is missing
    const body = await resp.text();
    expect(body.toLowerCase()).toMatch(/template|not found/);
  });
});

test.describe("Maker — bug hunt: concurrency & ordering", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string };
  let child: { id: string };
  let bomLineId: string;
  let recipeId: string;
  let locationId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    parent = await api.createProductTemplate(token, {
      name: `E2E-BugHunt-RaceParent-${Date.now()}`,
    });
    const childName = `E2E-BugHunt-RaceChild-${Date.now()}`;
    child = await api.createProductTemplate(token, { name: childName });
    // The order needs one of the child. Without it in stock the maker's
    // default shortage policy (warn) refuses the order before either racer
    // runs, and only a spec that had left the policy permissive let it pass.
    const storages = await api.listStorages(token);
    locationId = storages[0].id;
    await api.createItem(token, {
      name: childName,
      template_id: child.id,
      location_id: locationId,
      quantity: 1,
    });
    recipeId = await api.resolveDefaultRecipeId(token, parent.id);
    const line = await api.createBomLine(token, {
      recipe_id: recipeId,
      child_template_id: child.id,
      qty_per_batch: "1",
      unit: "kg",
    });
    bomLineId = line.id;
  });

  test.afterAll(async () => {
    if (bomLineId) {
      await api.deleteBomLine(token, bomLineId).catch(() => {});
    }
    await ctx.dispose();
  });

  test("concurrent cancel+complete: only one operation succeeds", async () => {
    const draft = await api.createProductionOrder(token, {
      output_template_id: parent.id,
      planned_qty: "1",
      output_location_id: locationId,
    });

    // Fire both at once. Only the first to commit can succeed; the helpers
    // reject on a refused request, so the second one must come back rejected
    // (status no longer DRAFT).
    const outcomes = await Promise.allSettled([
      api.cancelProductionOrder(token, draft.id),
      api.completeProductionOrder(token, draft.id),
    ]);

    // Exactly one operation won: zero means both were refused (the order
    // never got to run), two means the order was both cancelled and completed.
    const fulfilled = outcomes.filter((o) => o.status === "fulfilled");
    const rejected = outcomes.filter((o) => o.status === "rejected");
    expect(fulfilled).toHaveLength(1);
    expect(rejected).toHaveLength(1);

    // Cleanup
    await api.cancelProductionOrder(token, draft.id).catch(() => {});
  });

  test("rapidly duplicate (parent, child) lines: UNIQUE is enforced", async () => {
    // Try to create the same (parent, child) line 5 times in parallel.
    const results = await Promise.allSettled(
      Array(5)
        .fill(0)
        .map(() =>
          ctx.post(`/api/v1/maker/recipes/${recipeId}/bom-lines`, {
            headers: { Authorization: `Bearer ${token}` },
            data: {
              child_template_id: child.id,
              qty_per_batch: "1",
              unit: "kg",
            },
          }),
        ),
    );

    // At most one should have succeeded.
    const ok = results.filter(
      (r) =>
        r.status === "fulfilled" &&
        (r as PromiseFulfilledResponse<Response>).value.ok(),
    );
    expect(ok.length).toBeLessThanOrEqual(1);

    // Cleanup — only one line should exist
    const { items } = await api.listBomLines(token, parent.id);
    for (const line of items) {
      if (line.child_template_id === child.id) {
        await api.deleteBomLine(token, line.id).catch(() => {});
      }
    }
  });
});

test.describe("Maker — bug hunt: cross-org boundaries", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parentId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    const t = await api.createProductTemplate(token, {
      name: `E2E-BugHunt-XOrg-${Date.now()}`,
    });
    parentId = t.id;
  });

  test.afterAll(async () => {
    await api.deleteAllBomLinesForTemplate(token, parentId).catch(() => {});
    await ctx.dispose();
  });

  test("GET /maker/production/orders/<random-uuid> returns 404 (not 200 with data)", async () => {
    const resp = await ctx.get(
      "/api/v1/maker/production/orders/00000000-0000-0000-0000-000000000000",
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    expect(resp.status()).toBe(404);
  });

  test("GET /maker/bom/<random-uuid> returns 200 with empty (does not leak)", async () => {
    // No lines exist for an org-unique uuid; the endpoint returns
    // successfully with an empty list. This proves the response is scoped
    // by template/parent rather than exposing any cross-org rows.
    const resp = await ctx.get(
      `/api/v1/maker/bom/${"00000000-0000-0000-0000-000000000000"}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.items).toEqual([]);
    expect(body.total).toBe(0);
    expect(body.has_more).toBe(false);
  });

  test("cancel/complete a fabricated uuid returns 404 (does not silently succeed)", async () => {
    const complete = await ctx.post(
      "/api/v1/maker/production/orders/00000000-0000-0000-0000-000000000000/complete",
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(complete.status()).toBe(404);

    const cancel = await ctx.post(
      "/api/v1/maker/production/orders/00000000-0000-0000-0000-000000000000/cancel",
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(cancel.status()).toBe(404);
  });

  test("pricing/margin on fabricated uuid returns 404", async () => {
    const resp = await ctx.get(
      "/api/v1/maker/pricing/margin/00000000-0000-0000-0000-000000000000",
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(resp.status()).toBe(404);
  });
});

test.describe("Maker — bug hunt: response schema invariants", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string };
  let child: { id: string };

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    parent = await api.createProductTemplate(token, {
      name: `E2E-BugHunt-Schema-P-${Date.now()}`,
    });
    child = await api.createProductTemplate(token, {
      name: `E2E-BugHunt-Schema-C-${Date.now()}`,
    });
    // New-IA invariant: orders/previews require a recipe for the template.
    await api.createMakerRecipe(token, {
      output_template_id: parent.id,
      name: `E2E-BugHunt-Schema-Rec-${Date.now()}`,
    });
  });

  test.afterAll(async () => {
    await ctx.dispose();
  });

  test("preview returns CostBreakdownResponse shape", async () => {
    const storages = await api.listStorages(token);
    const body = await api.previewProduction(token, {
      output_template_id: parent.id,
      planned_qty: "1",
      output_location_id: storages[0].id,
    });
    expect(typeof body.output_template_id).toBe("string");
    expect(typeof body.planned_qty).toBe("string");
    expect(typeof body.total_cost).toBe("string");
    expect(Array.isArray(body.entries)).toBe(true);
    expect(Array.isArray(body.missing_cost_lines)).toBe(true);
    // numeric values are decimal strings
    for (const e of body.entries) {
      expect(typeof e.child_template_id).toBe("string");
      expect(typeof e.consumed_qty).toBe("string");
      expect(typeof e.unit).toBe("string");
      expect(["avco", "none"]).toContain(e.cost_source);
    }
  });

  test("production order create returns ProductionOrderRead shape (lines: [])", async () => {
    const storages = await api.listStorages(token);
    const body = await api.createProductionOrder(token, {
      output_template_id: parent.id,
      planned_qty: "1",
      output_location_id: storages[0].id,
    });
    expect(typeof body.id).toBe("string");
    expect(body.status).toBe("DRAFT");
    expect(body.total_cost).toBeNull();
    expect(body.notes).toBeNull();
    // DRAFT orders have no lines until completion
    if ("lines" in body) {
      expect(Array.isArray((body as { lines: unknown[] }).lines)).toBe(true);
    }

    // Cleanup
    await api.cancelProductionOrder(token, body.id).catch(() => {});
  });

  test("BoM list echoes the parent template on every line", async () => {
    const line = await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: child.id,
      qty_per_batch: "1.5",
      unit: "kg",
      yield_loss_pct: "0",
    });
    const listing = await api.listBomLines(token, parent.id);
    expect(listing.items.length).toBeGreaterThanOrEqual(1);
    expect(listing.items.every((l) => l.parent_template_id === parent.id)).toBe(
      true,
    );
    expect(listing.items[0].qty_per_batch).toBe("1.5000");

    await api.deleteBomLine(token, line.id).catch(() => {});
  });
});
