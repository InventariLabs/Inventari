import { useQuery } from "@tanstack/react-query";
import { uomsApi } from "@/lib/api/admin";
import { queryKeys } from "@/hooks/queries/keys";
import type { Uom, UomCategory } from "@/types";

/**
 * Returns all UoM categories with their associated UoMs.
 * Used in forms to determine field visibility (e.g., hide weight field for discrete units).
 */
export function useUoms() {
  return useQuery<UomCategory[]>({
    queryKey: queryKeys.uoms.categories,
    queryFn: () => uomsApi.getCategories(),
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes – UoMs rarely change
    gcTime: 10 * 60 * 1000,
  });
}

/**
 * Flat list of all UoMs (used in item/shopping list forms).
 * Use `useUoms()` for the category-grouped view (UomCategory[]).
 */
export function useFlatUoms() {
  return useQuery<Uom[]>({
    queryKey: queryKeys.uoms.all,
    queryFn: () => uomsApi.getAll(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Returns the UoM itself, so callers can reach its `factor` for conversions
 * instead of guessing from the symbol.
 */
export function findUom(
  categories: UomCategory[] | undefined,
  uomId: string | null | undefined,
): Uom | null {
  if (!categories || !uomId) return null;
  for (const cat of categories) {
    const found = cat.uoms?.find((u) => u.id === uomId);
    if (found) return found;
  }
  return null;
}

/**
 * Returns the category name for a given uom_id based on loaded UomCategories.
 * Useful for deciding field visibility (Weight/Volume vs discrete).
 */
export function getUomCategoryName(
  categories: UomCategory[] | undefined,
  uomId: string | null | undefined,
): string | null {
  if (!categories || !uomId) return null;
  for (const cat of categories) {
    if (cat.uoms?.some((u) => u.id === uomId)) {
      return cat.name;
    }
  }
  return null;
}

/**
 * Check if a uom_id refers to a continuous unit (Weight or Volume).
 * If so, 'quantity' IS the weight/volume and the separate 'weight' field should be hidden.
 */
export function isContinuousUom(
  categories: UomCategory[] | undefined,
  uomId: string | null | undefined,
): boolean {
  const name = getUomCategoryName(categories, uomId);
  return name === "Weight" || name === "Volume";
}

/**
 * The categories a product is counted in: one piece, or one bulk package.
 * They seed one unit per category, so the names are the contract here — the
 * same way `isContinuousUom` names Weight and Volume.
 */
const COUNTED_UOM_CATEGORIES = ["Unit", "Pack", "Can", "Bottle", "Box", "Bag"];

/**
 * Check if a uom_id refers to a counted unit — a piece or a bulk package
 * (pack, can, bottle, box, bag) — rather than a measured quantity. A counted
 * unit has no scale of its own, so a line in g/ml meets it only through the
 * product card's weight or volume per unit (ADR-015); the bridge reads the
 * template's measure the same way whichever counted category the unit is in.
 * Measured goods live in Weight, Volume and Length, where the card's
 * per-unit measure is not the way to another scale.
 */
export function isCountedUom(
  categories: UomCategory[] | undefined,
  uomId: string | null | undefined,
): boolean {
  const name = getUomCategoryName(categories, uomId);
  return name !== null && COUNTED_UOM_CATEGORIES.includes(name);
}
