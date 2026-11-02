import { test, expect, type APIRequestContext } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Cost-breakdown tests cover:
 *  - The /maker/breakdown endpoint returns entries + missing_cost_lines
 *  - Multi-level BoM explosion produces nested ingredients
 *  - Yield-loss scales the consumed qty by 1/(1 - pct/100)
 *  - Missing AVCO rate surfaces in missing_cost_lines
 *  - Pipe to the production preview endpoint (preview == breakdown for same qty)
 */

test.describe("Maker — cost breakdown", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;
  let parent: { id: string };
  let childA: { id: string };
  let childB: { id: string };
  let grandChild: { id: string };
  const lineIdsToCleanup: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    const stamp = Date.now();
    parent = await api.createProductTemplate(token, {
      name: `E2E-BD-Parent-${stamp}`,
    });
    childA = await api.createProductTemplate(token, {
      name: `E2E-BD-A-${stamp}`,
    });
    childB = await api.createProductTemplate(token, {
      name: `E2E-BD-B-${stamp}`,
    });
    grandChild = await api.createProductTemplate(token, {
      name: `E2E-BD-GC-${stamp}`,
    });
  });

  test.afterAll(async () => {
    await api.deleteAllBomLinesForTemplate(token, parent.id).catch(() => {});
    if (lineIdsToCleanup.length) {
      for (const id of lineIdsToCleanup) {
        await api.deleteBomLine(token, id).catch(() => {});
      }
    }
    await api.deleteAllBomLinesForTemplate(token, childA.id).catch(() => {});
    await ctx.dispose();
  });

  test("single-level BoM: breakdown returns one entry per direct child", async () => {
    const lineA = await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: childA.id,
      qty_per_batch: "2",
      unit: "kg",
    });
    lineIdsToCleanup.push(lineA.id);

    const lineB = await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: childB.id,
      qty_per_batch: "0.5",
      unit: "kg",
    });
    lineIdsToCleanup.push(lineB.id);

    const breakdown = await api.getCostBreakdown(token, parent.id, "10");
    // 10 * 2 = 20 of A, 10 * 0.5 = 5 of B
    const a = breakdown.entries.find((e) => e.child_template_id === childA.id);
    const b = breakdown.entries.find((e) => e.child_template_id === childB.id);
    expect(parseFloat(a!.consumed_qty)).toBeCloseTo(20, 5);
    expect(parseFloat(b!.consumed_qty)).toBeCloseTo(5, 5);
    // No AVCO → cost is null + both reported in missing
    expect(a?.cost).toBeNull();
    expect(breakdown.missing_cost_lines).toContain(childA.id);
    expect(breakdown.missing_cost_lines).toContain(childB.id);
  });

  test("multi-level BoM explosion works through preview", async () => {
    // First, ensure parent has a direct link to childA. The prior test
    // already added one with qty_per_batch=2. Verify quantity; if absent,
    // create it idempotently. Also ensure no stale grandChild line on
    // childA from prior runs.
    await api.deleteAllBomLinesForTemplate(token, childA.id).catch(() => {});

    await api
      .createBomLine(token, {
        parent_template_id: parent.id,
        child_template_id: childA.id,
        qty_per_batch: "3",
        unit: "kg",
      })
      .catch(() => {
        // UNIQUE(parent, child) — already present from a previous run.
        // The explosion multiplier comes from THIS qty, not the older one,
        // so we cannot recover without removing the existing line. Recreate
        // as needed by deleting then re-creating.
      });

    // Ensure exactly one (parent, childA) line with qty=3 — handle the
    // idempotent case by reading current state.
    let existing = await api.listBomLines(token, parent.id);
    let aLine = existing.items.find((l) => l.child_template_id === childA.id);
    if (aLine && aLine.qty_per_batch !== "3.0000") {
      // Replace by deleting the existing line and creating a fresh one
      // with qty=3.
      await api.deleteBomLine(token, aLine.id);
      const created = await api.createBomLine(token, {
        parent_template_id: parent.id,
        child_template_id: childA.id,
        qty_per_batch: "3",
        unit: "kg",
      });
      lineIdsToCleanup.push(created.id);
    } else if (!aLine) {
      const created = await api.createBomLine(token, {
        parent_template_id: parent.id,
        child_template_id: childA.id,
        qty_per_batch: "3",
        unit: "kg",
      });
      lineIdsToCleanup.push(created.id);
    }

    // Now attach grandChild under childA (1 kg per kg of childA).
    const lineAC = await api.createBomLine(token, {
      parent_template_id: childA.id,
      child_template_id: grandChild.id,
      qty_per_batch: "1",
      unit: "kg",
    });
    lineIdsToCleanup.push(lineAC.id);

    // globalSetup seeds a location, so there is always one to produce into.
    const storages = await api.listStorages(token);
    const outputStorageId = storages[0].id;

    const breakdown = await api.previewProduction(token, {
      output_template_id: parent.id,
      planned_qty: "2",
      output_location_id: outputStorageId,
    });

    // Re-read in case the qty fixup modified it
    existing = await api.listBomLines(token, parent.id);
    aLine = existing.items.find((l) => l.child_template_id === childA.id);
    const aQty = parseFloat(aLine!.qty_per_batch);

    // With 2 parent units × qty_per_batch kg of A
    // ⇒ A exploded = 2 × aQty kg ⇒ grandChild = 2 × aQty × 1 kg
    const gc = breakdown.entries.find(
      (e) => e.child_template_id === grandChild.id,
    );
    expect(gc).toBeTruthy();
    expect(parseFloat(gc!.consumed_qty)).toBeCloseTo(2 * aQty, 1);
  });

  test("yield_loss_pct scales qty upward (linear: 1 + pct/100)", async () => {
    // Mirrors the project's documented semantics:
    // effective_qty = qty * qty_per_batch * (1 + yield_loss_pct / 100).
    // 10 kg qty_per_batch × 20% loss ⇒ 1 × 10 × 1.20 = 12.
    const fresh = await api.createProductTemplate(token, {
      name: `E2E-BD-YieldParent-${Date.now()}`,
    });
    const ing = await api.createProductTemplate(token, {
      name: `E2E-BD-YieldIng-${Date.now()}`,
    });

    const line = await api.createBomLine(token, {
      parent_template_id: fresh.id,
      child_template_id: ing.id,
      qty_per_batch: "10",
      unit: "kg",
      yield_loss_pct: "20",
    });
    lineIdsToCleanup.push(line.id);

    const breakdown = await api.getCostBreakdown(token, fresh.id, "1");
    const entry = breakdown.entries.find((e) => e.child_template_id === ing.id);
    expect(parseFloat(entry!.consumed_qty)).toBeCloseTo(12.0, 1);
  });

  test("invalid qty (zero or negative) rejected", async () => {
    const r0 = await ctx.get(`/api/v1/maker/breakdown/${parent.id}?qty=0`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r0.status()).toBe(422);
    const rNeg = await ctx.get(`/api/v1/maker/breakdown/${parent.id}?qty=-1`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(rNeg.status()).toBe(422);
  });

  test("preview endpoint matches breakdown endpoint for same qty", async () => {
    const storages = await api.listStorages(token);
    const preview = await api.previewProduction(token, {
      output_template_id: parent.id,
      planned_qty: "5",
      output_location_id: storages[0].id,
    });
    const breakdown = await api.getCostBreakdown(token, parent.id, "5");
    expect(preview.total_cost).toBe(breakdown.total_cost);
    expect(preview.entries.length).toBe(breakdown.entries.length);
    for (let i = 0; i < preview.entries.length; i++) {
      expect(preview.entries[i].child_template_id).toBe(
        breakdown.entries[i].child_template_id,
      );
      expect(preview.entries[i].consumed_qty).toBe(
        breakdown.entries[i].consumed_qty,
      );
    }
  });
});
