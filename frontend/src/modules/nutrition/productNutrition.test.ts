import { describe, expect, it } from "vitest";
import type { Item } from "@/types";
import { productNutrition } from "./productNutrition";

const item = (
  productMeta: Record<string, unknown> | null,
  recordMeta: Record<string, unknown> | null = null,
) =>
  ({
    metadata: recordMeta,
    template: { meta_data: productMeta },
  }) as unknown as Pick<Item, "metadata" | "template">;

/**
 * A product's figures may be stored under the Open Food Facts names
 * (`energy_kcal`, `proteins`) as well as under the product's own; the recipe
 * nutrition reads both, and the product page reads the same figures.
 */
describe("productNutrition", () => {
  it("reads a product's figures stored under the provider's names", () => {
    expect(
      productNutrition(item({ nutrition: { energy_kcal: 321, proteins: 12 } })),
    ).toEqual({ calories_kcal: 321, protein_g: 12 });
  });

  it("reads the older calories name for the energy figure", () => {
    expect(productNutrition(item({ nutrition: { calories: 90 } }))).toEqual({
      calories_kcal: 90,
    });
  });

  it("takes the product's own name over the provider's on the product", () => {
    expect(
      productNutrition(
        item({ nutrition: { calories_kcal: 100, energy_kcal: 321 } }),
      ),
    ).toEqual({ calories_kcal: 100 });
  });

  it("takes the product's figure over the record's, and fills from the record", () => {
    expect(
      productNutrition(
        item(
          { nutrition: { energy_kcal: 321 } },
          { nutrition: { energy_kcal: 999, fat: 4 } },
        ),
      ),
    ).toEqual({ calories_kcal: 321, fat_g: 4 });
  });

  it("answers null when neither side knows a figure", () => {
    expect(productNutrition(item({ nutrition: {} }, {}))).toBeNull();
  });
});
