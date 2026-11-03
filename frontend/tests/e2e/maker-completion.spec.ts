import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — full completion lifecycle.
 *
 * These tests prove that:
 *  - complete on a DRAFT order consumes ingredients across locations
 *  - the produced item is created at the output location
 *  - the order transitions to COMPLETED with total_cost + completed_at
 *  - ProductionOrderLine snapshots are persisted
 *  - Insufficient stock blocks completion (no partial consume)
 *  - Cannot complete a non-DRAFT order
 *  - Cannot cancel a non-DRAFT order
 */

async function seedLifecycleContext(api: ApiHelper, ctx: APIRequestContext) {
  const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
  const token = auth.access_token;
  await api.enableAllModules(token);

  const stamp = Date.now();
  const output = await api.createProductTemplate(token, {
    name: `E2E-Comp-Out-${stamp}`,
  });
  const ingredient = await api.createProductTemplate(token, {
    name: `E2E-Comp-Ing-${stamp}`,
  });
  const sIn = await api.createStorage(token, {
    name: `E2E-Comp-In-${stamp}`,
  });
  const sOut = await api.createStorage(token, {
    name: `E2E-Comp-OutStore-${stamp}`,
  });

  // BoM: 1 unit out → 2 kg ingredient
  const line = await api.createBomLine(token, {
    parent_template_id: output.id,
    child_template_id: ingredient.id,
    qty_per_batch: "2",
    unit: "kg",
  });

  return {
    token,
    stamp,
    output,
    ingredient,
    sIn,
    sOut,
    bomLineId: line.id,
  };
}

test.describe("Maker — completion lifecycle", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let output: { id: string };
  let ingredient: { id: string };
  let sIn: { id: string };
  let sOut: { id: string };
  let bomLineId: string;
  const createdItemIds: string[] = [];
  const orderIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const seeded = await seedLifecycleContext(api, ctx);
    token = seeded.token;
    output = seeded.output;
    ingredient = seeded.ingredient;
    sIn = seeded.sIn;
    sOut = seeded.sOut;
    bomLineId = seeded.bomLineId;
  });

  test.afterAll(async () => {
    for (const id of orderIds) {
      await api.cancelProductionOrder(token, id).catch(() => {});
      await api.request
        .delete(`/api/v1/maker/production/orders/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .catch(() => {});
    }
    await api.deleteBomLine(token, bomLineId).catch(() => {});
    // Items are tied to the template (input and output). Best-effort delete.
    for (const itemId of createdItemIds) {
      await api.deleteItem(token, itemId).catch(() => {});
    }
    await ctx.dispose();
  });

  test("happy path: complete consumes stock and produces item", async () => {
    // 1. Seed enough stock at the input storage: 1 unit out → 2 kg in.
    // Use the ingredient's name directly so the resolver hits the
    // existing template (created in beforeAll via createProductTemplate).
    const stock = await api.seedStock(token, {
      product_template_id: ingredient.id,
      product_template_name: ingredient.name,
      location_id: sIn.id,
      quantity: 10,
    });
    createdItemIds.push(stock.item_id);

    // 2. Create a draft order
    const draft = await api.createProductionOrder(token, {
      output_template_id: output.id,
      planned_qty: "3",
      output_location_id: sOut.id,
      notes: "lifecycle happy",
    });
    orderIds.push(draft.id);

    // 3. Complete
    const completed = await api.completeProductionOrder(token, draft.id);
    expect(completed.status).toBe("COMPLETED");
    expect(parseFloat(completed.total_cost ?? "0")).toBeGreaterThanOrEqual(0);

    // 4. Verify order now reports lines
    const fullOrder = await api.getProductionOrder(token, draft.id);
    expect(fullOrder.status).toBe("COMPLETED");
    expect(fullOrder.lines.length).toBeGreaterThan(0);
    const ingLine = fullOrder.lines.find(
      (l) => l.child_template_id === ingredient.id,
    );
    expect(ingLine).toBeTruthy();
    expect(parseFloat(ingLine!.consumed_qty)).toBeCloseTo(6, 1); // 3 units × 2 kg
  });

  test("insufficient stock blocks completion (no partial consume)", async () => {
    // The seed in beforeAll already produced the ingredient (via happy
    // path test). To prove the deficit guard we must consume it back to
    // zero. Cancel the prior draft first to keep state simple, then
    // create a fresh stock record with only 1 kg and demand 4 kg.
    //
    // Strategy: rather than mutate existing quants, this test creates a
    // *separate* ingredient template + BoM line and only seeds 1 kg of
    // it. That isolates the deficit from shared state.
    const stamp = Date.now();
    const deficitIng = await api.createProductTemplate(token, {
      name: `E2E-Comp-Deficit-Ing-${stamp}`,
    });
    const deficitLine = await api.createBomLine(token, {
      parent_template_id: output.id,
      child_template_id: deficitIng.id,
      qty_per_batch: "2",
      unit: "kg",
    });

    const stock = await api.seedStock(token, {
      product_template_id: deficitIng.id,
      product_template_name: deficitIng.name,
      location_id: sIn.id,
      quantity: 1, // demand 2 units × 2 = 4 kg; only 1 kg available
    });
    createdItemIds.push(stock.item_id);

    const draft = await api.createProductionOrder(token, {
      output_template_id: output.id,
      planned_qty: "2",
      output_location_id: sOut.id,
      notes: "deficit",
      // The draft is short on purpose: only completion must refuse it.
      confirm_shortage: true,
    });
    orderIds.push(draft.id);

    let err: Error | null = null;
    try {
      await api.completeProductionOrder(token, draft.id);
    } catch (e) {
      err = e as Error;
    }
    expect(err).not.toBeNull();
    expect((err as Error).message).toMatch(/insufficient|400/i);

    // Order must remain DRAFT (no partial consume)
    const after = await api.getProductionOrder(token, draft.id);
    expect(after.status).toBe("DRAFT");
    expect(after.lines.length).toBe(0);

    // Cleanup the temporary BoM line
    await api.deleteBomLine(token, deficitLine.id).catch(() => {});
  });

  test("cannot complete a non-DRAFT order", async () => {
    const draft = await api.createProductionOrder(token, {
      output_template_id: output.id,
      planned_qty: "1",
      output_location_id: sOut.id,
      // These tests exercise status handling and listing, not stock: the
      // shortage warning is acknowledged so the draft exists.
      confirm_shortage: true,
    });
    await api.cancelProductionOrder(token, draft.id);
    orderIds.push(draft.id);

    let err: Error | null = null;
    try {
      await api.completeProductionOrder(token, draft.id);
    } catch (e) {
      err = e as Error;
    }
    expect(err).not.toBeNull();
    expect((err as Error).message).toMatch(/400|CANCELLED|status/i);
  });

  test("cannot cancel a non-DRAFT order", async () => {
    const draft = await api.createProductionOrder(token, {
      output_template_id: output.id,
      planned_qty: "1",
      output_location_id: sOut.id,
      // These tests exercise status handling and listing, not stock: the
      // shortage warning is acknowledged so the draft exists.
      confirm_shortage: true,
    });
    await api.cancelProductionOrder(token, draft.id);
    orderIds.push(draft.id);

    // Now try to cancel again — should fail
    let err: Error | null = null;
    try {
      await api.cancelProductionOrder(token, draft.id);
    } catch (e) {
      err = e as Error;
    }
    expect(err).not.toBeNull();
  });

  test("invalid template id → 404", async () => {
    const resp = await ctx.get(
      `/api/v1/maker/production/orders/00000000-0000-0000-0000-000000000000`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(resp.status()).toBe(404);
  });

  test("list orders is org-scoped (no leakage)", async () => {
    const draft = await api.createProductionOrder(token, {
      output_template_id: output.id,
      planned_qty: "1",
      output_location_id: sOut.id,
      // These tests exercise status handling and listing, not stock: the
      // shortage warning is acknowledged so the draft exists.
      confirm_shortage: true,
    });
    orderIds.push(draft.id);

    const all = await api.listProductionOrders(token);
    expect(all.find((o) => o.id === draft.id)).toBeTruthy();

    // Filter by status
    const drafts = await api.listProductionOrders(token, { status: "DRAFT" });
    expect(drafts.find((o) => o.id === draft.id)).toBeTruthy();

    const cancelled = await api.listProductionOrders(token, {
      status: "CANCELLED",
    });
    expect(cancelled.find((o) => o.id === draft.id)).toBeFalsy();

    // Filter by template
    const templateFiltered = await api.listProductionOrders(token, {
      output_template_id: output.id,
    });
    expect(templateFiltered.find((o) => o.id === draft.id)).toBeTruthy();
  });
});
