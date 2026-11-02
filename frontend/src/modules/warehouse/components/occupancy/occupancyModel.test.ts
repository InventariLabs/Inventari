import { describe, expect, it } from "vitest";
import { floor } from "@/test/factories/occupancy";
import {
  hitsAt,
  onlyProduct,
  passesFilter,
  pathOf,
  visibleNodeIds,
  visibleNodes,
} from "./occupancyModel";

const byName = (name: string) => floor.nodes.find((n) => n.name === name)!;

describe("passesFilter", () => {
  it("counts a shelf over its limit as full", () => {
    expect(passesFilter(byName("Fridge C").cell!, "full")).toBe(true);
    expect(passesFilter(byName("Fridge A").cell!, "full")).toBe(false);
  });

  it("keeps the over-limit filter to shelves past their limit", () => {
    expect(passesFilter(byName("Fridge C").cell!, "over")).toBe(true);
    expect(passesFilter(byName("Fridge B").cell!, "over")).toBe(false);
  });

  it("tells an empty shelf from one nobody limited", () => {
    expect(passesFilter(byName("Fridge D").cell!, "empty")).toBe(true);
    expect(passesFilter(byName("Rack 1").cell!, "noLimit")).toBe(true);
    expect(passesFilter(byName("Rack 1").cell!, "empty")).toBe(false);
  });
});

/** What a search for Gouda answers: the two fridges that hold it. */
const goudaHits = new Map([
  [
    "Fridge B",
    [{ productId: "p-Gouda", name: "Gouda", quantity: "12", unit: "pcs" }],
  ],
  [
    "Fridge C",
    [{ productId: "p-Gouda", name: "Gouda", quantity: "48", unit: "pcs" }],
  ],
]);

describe("hitsAt", () => {
  it("gives what the search found on a shelf", () => {
    expect(hitsAt(goudaHits, "Fridge B")).toEqual([
      { productId: "p-Gouda", name: "Gouda", quantity: "12", unit: "pcs" },
    ]);
  });

  it("finds nothing on another shelf, or without a search", () => {
    expect(hitsAt(goudaHits, "Rack 1")).toEqual([]);
    expect(hitsAt(null, "Fridge B")).toEqual([]);
  });
});

describe("onlyProduct", () => {
  it("names the product of a shelf that holds one", () => {
    expect(onlyProduct(byName("Rack 1").cell!)?.product_template_name).toBe(
      "Flour",
    );
  });

  it("names none on a shelf of two products, or of none", () => {
    expect(onlyProduct(byName("Fridge B").cell!)).toBeNull();
    expect(onlyProduct(byName("Fridge D").cell!)).toBeNull();
  });
});

describe("visibleNodeIds", () => {
  it("filters nothing when nothing is asked", () => {
    expect(visibleNodeIds(floor.nodes, "all", null)).toBeNull();
  });

  it("keeps a passing shelf with every location above it", () => {
    const ids = visibleNodeIds(floor.nodes, "over", null);
    expect([...ids!].sort()).toEqual(["Cold", "Fridge C", "Main"]);
  });

  it("keeps the shelves that hold the searched product", () => {
    const ids = visibleNodeIds(floor.nodes, "all", goudaHits);
    expect([...ids!].sort()).toEqual(["Cold", "Fridge B", "Fridge C", "Main"]);
  });

  it("combines the filter with the search", () => {
    const ids = visibleNodeIds(floor.nodes, "over", goudaHits);
    expect([...ids!].sort()).toEqual(["Cold", "Fridge C", "Main"]);
  });
});

describe("visibleNodes", () => {
  it("hides everything under a folded location and nothing beside it", () => {
    const rows = visibleNodes(floor.nodes, null, new Set(["Cold"]));
    expect(rows.map((n) => n.name)).toEqual(["Main", "Cold", "Dry", "Rack 1"]);
  });

  it("shows only the branch a filter leaves", () => {
    const visible = visibleNodeIds(floor.nodes, "noLimit", null);
    const rows = visibleNodes(floor.nodes, visible, new Set());
    expect(rows.map((n) => n.name)).toEqual(["Main", "Dry", "Rack 1"]);
  });
});

describe("pathOf", () => {
  it("names the way down from the warehouse", () => {
    const byId = new Map(floor.nodes.map((n) => [n.location_id, n]));
    expect(pathOf(byId, byName("Fridge A"))).toBe("Main › Cold › Fridge A");
  });
});
