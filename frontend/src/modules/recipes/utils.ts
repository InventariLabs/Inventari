import type { RecipeIngredient } from "@/modules/recipes/types/core";
import { formatQuantityLocale, toAmount } from "@/utils/formatters";

export const COUNTABLE_UOMS = new Set([
  "pcs",
  "szt",
  "szt.",
  "pc",
  "piece",
  "pieces",
  "sztuk",
  "jajko",
  "jajka",
]);

/**
 * Fraction map: decimal → vulgar fraction unicode.
 * Tolerance of ±0.02 for matching.
 */
const FRACTIONS: [number, string][] = [
  [0.125, "⅛"],
  [0.25, "¼"],
  [1 / 3, "⅓"],
  [0.375, "⅜"],
  [0.5, "½"],
  [0.625, "⅝"],
  [2 / 3, "⅔"],
  [0.75, "¾"],
  [0.875, "⅞"],
];

const FRAC_TOLERANCE = 0.02;

/**
 * Format a quantity in recipe-friendly style:
 *  - whole numbers: "3"
 *  - recognized fractions: "½", "1½", "2⅓"
 *  - otherwise: up to 1 decimal ("1.2"), or up to 2 for tiny amounts ("0.15")
 */
export const fmtQty = (qty: number): string => {
  if (qty <= 0) return "0";

  const whole = Math.floor(qty);
  const frac = qty - whole;

  // Exact whole number
  if (frac < FRAC_TOLERANCE) return String(whole);

  // Try to match a vulgar fraction
  for (const [val, symbol] of FRACTIONS) {
    if (Math.abs(frac - val) < FRAC_TOLERANCE) {
      return whole > 0 ? `${whole}${symbol}` : symbol;
    }
  }

  // Close to next whole number (e.g. 2.98 → 3)
  if (1 - frac < FRAC_TOLERANCE) return String(whole + 1);

  // Fallback: smart decimal rounding — the same places the fixed-point
  // calls kept, written with the reader's decimal mark.
  return formatQuantityLocale(String(qty), qty < 1 ? 2 : 1);
};

export const isFractionalCountable = (
  qty: number,
  uom: string | null,
): boolean => {
  const unit = (uom ?? "").toLowerCase();
  return (
    COUNTABLE_UOMS.has(unit) &&
    !Number.isInteger(parseFloat(Number(qty).toFixed(3)))
  );
};

/**
 * Weight/volume units whose small amounts read as seasoning. The recipe
 * card's collapsed section and the import review's "Spice" chip ask the same
 * question, so they read one answer instead of a copy each.
 */
const SPICE_UOMS = new Set(["g", "ml", "mg"]);
const SPICE_THRESHOLD = 10;

/**
 * Whether an amount is small enough to fold away as seasoning.
 *
 * Pieces are never spices by amount: the card used to send every countable
 * ingredient at one or less into the collapsed section — one egg, one onion,
 * half a carton of milk — so a main ingredient disappeared under the heading
 * that says "seasonings". A piece the cook means as a spice is marked as one
 * in the import review, and the mark travels with the recipe: the card folds
 * a row in when the mark is set or the amount reads as seasoning.
 */
export const isSpiceQuantity = (
  quantity: number,
  uomSymbol: string | null,
): boolean => {
  if (uomSymbol == null) return false;
  return SPICE_UOMS.has(uomSymbol.toLowerCase()) && quantity <= SPICE_THRESHOLD;
};

/**
 * Find serving counts in range [1..max] where all countable ingredients yield whole numbers.
 * Skips `currentServings` itself.
 */
export function findCleanServings(
  baseServings: number,
  ingredients: RecipeIngredient[],
  currentServings: number,
  maxS = 12,
): number[] {
  const countable = ingredients.filter(
    (i) =>
      COUNTABLE_UOMS.has((i.uom_symbol ?? "").toLowerCase()) &&
      (toAmount(i.quantity) ?? 0) > 0,
  );
  if (countable.length === 0) return [];

  const upper = Math.max(maxS, currentServings + 4);
  const result: number[] = [];
  for (let s = 1; s <= upper; s++) {
    if (s === currentServings) continue;
    const allWhole = countable.every((ing) => {
      const qty = ((toAmount(ing.quantity) ?? 0) * s) / baseServings;
      return Math.abs(qty - Math.round(qty)) < 0.001;
    });
    if (allWhole) result.push(s);
  }
  return result;
}

/**
 * Whether the picking row has no way of reaching stock: the ingredient points
 * at no product and its name matched nothing either. Linking is the answer
 * only here — an ingredient that is linked but sold out is "missing", which
 * the row's badge already says.
 */
export const needsProductLink = (item: {
  is_linked: boolean;
  recommended_item_id: string | null;
}): boolean => item.is_linked === false && item.recommended_item_id == null;
