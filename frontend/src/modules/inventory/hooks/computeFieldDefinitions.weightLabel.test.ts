import { describe, it, expect } from "vitest";
import { computeFieldDefinitions } from "./computeFieldDefinitions";

const baseContext = {
  selectedCategory: undefined,
  selectedStorage: undefined,
} as const;

const weightLabel = (uomCategoryName: string | null) =>
  computeFieldDefinitions({ ...baseContext, uomCategoryName }).find(
    (f) => f.key === "weight",
  )?.label;

/**
 * The weight field describes one counted unit, and its label names the unit
 * the product is counted in: a pack is not a piece.
 */
describe("computeFieldDefinitions — the weight field follows the unit", () => {
  it.each(["Pack", "Can", "Bottle", "Box", "Bag"])(
    "says per package for a unit of the %s category",
    (category) => {
      expect(weightLabel(category)).toBe("items:itemWeightPerPackage");
    },
  );

  it("keeps per piece for a piece and where no unit is chosen yet", () => {
    expect(weightLabel("Unit")).toBe("items:itemWeightPerUnit");
    expect(weightLabel(null)).toBe("items:itemWeightPerUnit");
  });
});
