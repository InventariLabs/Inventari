import { describe, it, expect } from "vitest";
import {
  fmtQty,
  isFractionalCountable,
  isSpiceQuantity,
  findCleanServings,
} from "./utils";
import type { RecipeIngredient } from "@/modules/recipes/types/core";

// ─── fmtQty ──────────────────────────────────────────────────────────────────

describe("fmtQty", () => {
  it("returns whole numbers as-is", () => {
    expect(fmtQty(2)).toBe("2");
    expect(fmtQty(10)).toBe("10");
    expect(fmtQty(0)).toBe("0");
  });

  it("formats common fractions as vulgar fraction symbols", () => {
    expect(fmtQty(0.25)).toBe("¼");
    expect(fmtQty(0.5)).toBe("½");
    expect(fmtQty(0.75)).toBe("¾");
    expect(fmtQty(1 / 3)).toBe("⅓");
    expect(fmtQty(2 / 3)).toBe("⅔");
    expect(fmtQty(0.125)).toBe("⅛");
  });

  it("formats mixed numbers with fractions", () => {
    expect(fmtQty(1.5)).toBe("1½");
    expect(fmtQty(2.5)).toBe("2½");
    expect(fmtQty(1 + 1 / 3)).toBe("1⅓");
    expect(fmtQty(2 + 2 / 3)).toBe("2⅔");
    expect(fmtQty(3.25)).toBe("3¼");
    expect(fmtQty(1.75)).toBe("1¾");
  });

  it("falls back to smart decimal for non-fraction values", () => {
    expect(fmtQty(1.666666667)).toBe("1⅔");
    expect(fmtQty(0.1)).toBe("0.1");
    expect(fmtQty(3.1)).toBe("3.1");
    expect(fmtQty(0.15)).toBe("0.15");
  });

  it("rounds near-whole values up", () => {
    expect(fmtQty(2.99)).toBe("3");
    expect(fmtQty(4.98)).toBe("5");
  });
});

// ─── isFractionalCountable ────────────────────────────────────────────────────

describe("isFractionalCountable", () => {
  const countableUnits = [
    "szt",
    "szt.",
    "pcs",
    "pc",
    "piece",
    "pieces",
    "sztuk",
    "jajko",
    "jajka",
  ];

  it.each(countableUnits)('detects fractional for UOM "%s"', (uom) => {
    expect(isFractionalCountable(2.5, uom)).toBe(true);
    expect(isFractionalCountable(0.333, uom)).toBe(true);
  });

  it.each(countableUnits)(
    'returns false for whole number with UOM "%s"',
    (uom) => {
      expect(isFractionalCountable(1, uom)).toBe(false);
      expect(isFractionalCountable(2, uom)).toBe(false);
      expect(isFractionalCountable(10, uom)).toBe(false);
    },
  );

  it("returns false for non-countable UOM even if fractional", () => {
    expect(isFractionalCountable(2.5, "kg")).toBe(false);
    expect(isFractionalCountable(2.5, "l")).toBe(false);
    expect(isFractionalCountable(2.5, "g")).toBe(false);
    expect(isFractionalCountable(2.5, null)).toBe(false);
  });

  it("is case-insensitive for UOM", () => {
    expect(isFractionalCountable(2.5, "SZT")).toBe(true);
    expect(isFractionalCountable(2.5, "Pcs")).toBe(true);
  });

  it("returns false for a value that looks fractional but rounds to integer at 3 decimals", () => {
    // 1.0004 rounds to 1.000 which is integer
    expect(isFractionalCountable(1.0004, "szt")).toBe(false);
  });
});

// ─── isSpiceQuantity ─────────────────────────────────────────────────────────

describe("isSpiceQuantity", () => {
  it("treats a small weight or volume as seasoning", () => {
    expect(isSpiceQuantity(5, "g")).toBe(true);
    expect(isSpiceQuantity(10, "ml")).toBe(true);
    expect(isSpiceQuantity(3, "mg")).toBe(true);
  });

  it("keeps an amount over the threshold an ingredient", () => {
    expect(isSpiceQuantity(15, "g")).toBe(false);
    expect(isSpiceQuantity(11, "ml")).toBe(false);
  });

  it("never treats pieces as seasoning by amount", () => {
    // One egg, one onion, half a carton of milk — each is a main ingredient,
    // and the card used to hide all of them under the spices heading.
    expect(isSpiceQuantity(1, "pcs")).toBe(false);
    expect(isSpiceQuantity(0.5, "szt")).toBe(false);
    expect(isSpiceQuantity(1, "jajko")).toBe(false);
  });

  it("ignores units that are neither weight nor volume", () => {
    expect(isSpiceQuantity(1, "kg")).toBe(false);
    expect(isSpiceQuantity(5, null)).toBe(false);
  });

  it("reads the unit symbol case-insensitively", () => {
    expect(isSpiceQuantity(5, "G")).toBe(true);
    expect(isSpiceQuantity(5, "ML")).toBe(true);
  });
});

// ─── findCleanServings ────────────────────────────────────────────────────────

const makeIngredient = (
  quantity: number,
  uom_symbol: string,
): RecipeIngredient => ({
  id: crypto.randomUUID(),
  recipe_id: "r1",
  name: "Test",
  template_id: null,
  ingredient_group_name: null,
  quantity: String(quantity),
  uom_id: null,
  uom_symbol,
  is_optional: false,
  is_spice: false,
  sort_order: 0,
  calories_kcal_per_100g: null,
  picking_skip: null,
  display_text: null,
  original_quantity: null,
  original_unit_text: null,
  price: null,
  price_uom_id: null,
  price_currency: null,
  allergens: [],
});

describe("findCleanServings", () => {
  it("returns empty array when there are no countable ingredients", () => {
    const ingredients = [makeIngredient(200, "g"), makeIngredient(0.5, "l")];
    expect(findCleanServings(4, ingredients, 3)).toEqual([]);
  });

  it("returns only multiples of base when ingredient qty = 1 (1 jajko / 4 porcje)", () => {
    // 1 jajko per 4 porcje → s=1: 0.25, s=2: 0.5, s=3: 0.75, s=5: 1.25...
    // Clean (multiples of 4): 4, 8 etc.  maxS default 12 → upper = max(12, 3+4) = 12
    const ingredients = [makeIngredient(1, "jajko")];
    const result = findCleanServings(4, ingredients, 3, 12);
    expect(result.every((s) => Number.isInteger(s / 4))).toBe(true);
    // Multiples of 4 in 1..12 except 3 (currentServings): 4, 8, 12
    expect(result).toContain(4);
    expect(result).toContain(8);
    expect(result).not.toContain(3); // skips currentServings
  });

  it("finds clean servings for standard recipe (2 jajka / 4 porcje)", () => {
    const ingredients = [makeIngredient(2, "jajka"), makeIngredient(300, "g")];
    // 2 jajka na 4 porcje → 0.5 per porcja → clean: 2, 4, 6, 8...
    const result = findCleanServings(4, ingredients, 3);
    expect(result).toContain(2);
    expect(result).toContain(4);
    expect(result).toContain(6);
    expect(result).not.toContain(3);
    expect(result).not.toContain(1); // 1 * 2/4 = 0.5 — not whole
  });

  it("excludes the current servings from results", () => {
    const ingredients = [makeIngredient(2, "szt")];
    const result = findCleanServings(2, ingredients, 4);
    expect(result).not.toContain(4);
  });

  it("returns empty array when no ingredients are countable (zero quantity)", () => {
    const ingredients = [makeIngredient(0, "szt")];
    expect(findCleanServings(4, ingredients, 3)).toEqual([]);
  });

  it("handles base = 1 (per-serving recipe)", () => {
    const ingredients = [makeIngredient(1, "szt")];
    // Every serving is a whole number
    const result = findCleanServings(1, ingredients, 3, 8);
    expect(result).toEqual([1, 2, 4, 5, 6, 7, 8]);
  });

  it("extends range beyond maxS when currentServings is large", () => {
    const ingredients = [makeIngredient(2, "pcs")];
    // currentServings=15 → upper = max(12, 15+4) = 19
    const result = findCleanServings(2, ingredients, 15, 12);
    expect(result.every((s) => s <= 19)).toBe(true);
  });
});
