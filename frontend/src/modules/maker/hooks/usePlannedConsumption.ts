import { useMemo } from "react";
import { useCostBreakdown } from "@/modules/maker/hooks/useCostBreakdown";
import { useMakerRecipe } from "@/modules/maker/hooks/useRecipes";
import type {
  ShortageEntry,
  ProductionOrder,
} from "@/modules/maker/types/maker";

/**
 * What a production order will take, before it takes anything.
 *
 * Order lines are written at completion, so a draft has none and its
 * ingredient section could only say "nothing captured yet" — the same words a
 * BOM with nothing in it earns. Both answers are available beforehand: the
 * breakdown of the formula this order runs, and whether that formula lists
 * anything at all.
 *
 * The breakdown is asked for `order.recipe_id`, not for the product's default
 * formula: completion consumes by the order's, and the two differ as soon as
 * a product has a second one.
 *
 * Which ingredients are short is not recomputed here: the server answers
 * with the refusal's own list (`shortage_items`), the same one completion
 * refuses with. A browser-side forecast used to sit next to the server's
 * banner and disagree with it — different batches, no location context —
 * and the rows a run would be refused over carried no marker at all.
 */
export function usePlannedConsumption(order: ProductionOrder | undefined) {
  const { data: recipe } = useMakerRecipe(order?.recipe_id ?? undefined);
  const isPlanned = order?.status === "DRAFT";
  const { data: breakdown } = useCostBreakdown(
    isPlanned ? order?.output_template_id : undefined,
    order?.planned_qty ?? "0",
    order?.recipe_id,
  );

  const shortages = useMemo(() => {
    const map = new Map<string, ShortageEntry>();
    for (const item of order?.shortage_items ?? []) {
      map.set(item.child_template_id, item);
    }
    return map;
  }, [order?.shortage_items]);

  return {
    /** Nothing has left stock yet, so the table is a forecast. */
    isPlanned,
    entries: breakdown?.entries,
    /** The run would consume nothing — the server refuses such a run. */
    bomIsEmpty: recipe?.lines?.length === 0,
    /** Ingredients the planned consumption cannot cover, by template id —
     * the refusal's own list, rows included. */
    shortages,
    hasShortage: shortages.size > 0,
  };
}
