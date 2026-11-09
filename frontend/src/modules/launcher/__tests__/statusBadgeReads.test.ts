import { describe, expect, it } from "vitest";

import { moduleRegistry } from "@/lib/moduleRegistry";

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../*/module.ts", { eager: true });

/**
 * The launcher asks a tile's status only of a role holding the read the
 * module names for it. A badge that names none is asked of everyone, and a
 * role without the read then sees "Status could not be read" on the tile —
 * the home screen of a custom role holding the warehouse's read said so on
 * the Inventory and Equipment tiles.
 *
 * The keys are the reads the badges' endpoints ask for: the attention counts
 * answer `items:read`, the warranty alerts and the floor's queue the
 * equipment and warehouse routers' own reads.
 */
describe("a launcher badge names the read it asks for", () => {
  const badged = moduleRegistry
    .getAllRegisteredModules()
    .map((name) => moduleRegistry.getModule(name)!)
    .filter((module) => module.useStatusBadge !== undefined);

  it("covers every module whose tile carries a badge", () => {
    expect(
      Object.fromEntries(
        badged.map((module) => [module.name, module.statusBadgePermission]),
      ),
    ).toEqual({
      inventory: "items:read",
      equipment: "equipment:read",
      warehouse: "warehouse:read",
    });
  });
});
