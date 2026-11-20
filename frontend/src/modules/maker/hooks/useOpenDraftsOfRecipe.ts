import { useProductionOrders } from "@/modules/maker/hooks/useProduction";

/**
 * How many open drafts read a BOM when they close. A draft takes its
 * ingredients and yield from the BOM at that moment, so an edit to the BOM
 * changes each of them; the confirmations of such edits say how many.
 */
export function useOpenDraftsOfRecipe(
  recipe: { id: string; output_template_id: string },
  /** Read only while a confirmation that quotes the count is open. */
  enabled: boolean,
): number {
  const drafts = useProductionOrders(
    {
      status: "DRAFT",
      output_template_id: recipe.output_template_id,
      limit: 200,
    },
    { enabled },
  );
  return (drafts.data?.items ?? []).filter(
    (order) => order.recipe_id === recipe.id,
  ).length;
}
