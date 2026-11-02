import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import "../module";
import "@/modules/stock_takes/module";

describe("inventory's stock-take entries", () => {
  const inventory = moduleRegistry.getModule("inventory");

  it("offers the nav entry only while the stock_takes module is on", () => {
    const item = inventory?.moduleNav?.items.find(
      (i) => i.path === "/inventory/stock-takes",
    );
    expect(item?.requiresModules).toEqual(["stock_takes"]);
  });

  it("leaves the stock-take screens to the stock_takes module, in its shell", () => {
    // Inventory links to them without importing them: the routes are
    // stock_takes', hosted in the inventory shell and mounted only while
    // that module is on.
    expect(
      (inventory?.routes ?? []).filter((r) =>
        r.path.startsWith("/inventory/stock-takes"),
      ),
    ).toEqual([]);
    const hosted = (
      moduleRegistry.getModule("stock_takes")?.routes ?? []
    ).filter((r) => r.path.startsWith("/inventory/stock-takes"));
    expect(hosted).toHaveLength(4);
    for (const route of hosted) expect(route.shell).toBe("inventory");
  });
});
