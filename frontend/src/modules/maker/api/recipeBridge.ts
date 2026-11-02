import { api } from "@/lib/api/client";
import type { ProductionOrder, ProductionOrderCreate } from "../types/maker";

/**
 * The bridge from a culinary recipe to production.
 *
 * The "Cook a batch for stock" sheet opens on the culinary recipe page but
 * produces this module's records: a snapshot maker recipe (one-way, frozen)
 * and a DRAFT production order. The sheet is this module's, contributed to
 * the recipe page through the `recipe_cook_for_stock` slot.
 */

export interface MakerRecipeFromCulinary {
  /** Culinary recipe id — stamped as source_recipe_id (plain UUID, no FK). */
  source_recipe_id: string;
  /** Product template that the batch produces. */
  output_template_id: string;
  /** Optional overrides; both default to the culinary recipe's values. */
  name?: string;
  batch_yield_qty?: string;
  batch_yield_uom_id?: string | null;
}

/** Maker recipe detail subset consumed by the bridge flow. */
export interface MakerRecipeBridgeResult {
  id: string;
  name: string;
  output_template_id: string;
  source_recipe_id: string | null;
  lines: Array<{ id: string }>;
  /**
   * Whether this call is what created the snapshot. The endpoint is
   * idempotent, so a second "cook for stock" on the same pair hands back the
   * first answer — and a caller cleaning up after an abandoned bridge must
   * not delete a record it did not make.
   */
  created: boolean;
}

/**
 * Create (or reuse — idempotent per output × source pair) the maker recipe
 * snapshot of a culinary recipe. Returns the maker recipe id to pass to the
 * production-order create call.
 */
export async function createMakerRecipeFromCulinary(
  data: MakerRecipeFromCulinary,
): Promise<MakerRecipeBridgeResult> {
  const response = await api.post<MakerRecipeBridgeResult>(
    "/maker/recipes/from-recipe",
    data,
  );
  return response.data;
}

/**
 * Delete a snapshot the bridge created and nobody adopted.
 *
 * The maker module refuses to delete a recipe referenced by a production
 * order, so this can only ever remove the litter of an abandoned attempt.
 */
export async function discardBridgeRecipe(recipeId: string): Promise<void> {
  await api.delete(`/maker/recipes/${recipeId}`);
}

/** Create a DRAFT production order against a maker recipe. */
export async function createProductionOrderFromBridge(
  data: ProductionOrderCreate,
): Promise<ProductionOrder> {
  const response = await api.post<ProductionOrder>(
    "/maker/production/orders",
    data,
  );
  return response.data;
}
