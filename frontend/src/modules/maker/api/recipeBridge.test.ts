import { describe, it, expect } from "vitest";
import { recordRequests } from "@/test/requestLog";
import {
  createMakerRecipeFromCulinary,
  createProductionOrderFromBridge,
  discardBridgeRecipe,
} from "./recipeBridge";

/**
 * "Cook a batch for stock" turns a culinary recipe into this module's records
 * through three calls. Each must hit its own path: the discard call deletes a
 * record, so a wrong path deletes the wrong thing.
 */
describe("recipe → maker bridge", () => {
  it("snapshots a culinary recipe into a maker recipe", async () => {
    const log = recordRequests(() => ({ id: "m1", created: true }));
    const body = { source_recipe_id: "r1", output_template_id: "t1" };
    await expect(createMakerRecipeFromCulinary(body)).resolves.toMatchObject({
      id: "m1",
      created: true,
    });
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/maker/recipes/from-recipe",
      body,
    });
  });

  it("discards only the snapshot it names", async () => {
    const log = recordRequests(() => undefined);
    await discardBridgeRecipe("m1");
    expect(log).toHaveLength(1);
    expect(log[0]).toMatchObject({
      method: "DELETE",
      path: "/maker/recipes/m1",
    });
  });

  it("opens a draft production order against the snapshot", async () => {
    const log = recordRequests(() => ({ id: "o1" }));
    const body = { recipe_id: "m1", batches: "1" };
    await expect(
      createProductionOrderFromBridge(body as never),
    ).resolves.toEqual({ id: "o1" });
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/maker/production/orders",
      body,
    });
  });
});
