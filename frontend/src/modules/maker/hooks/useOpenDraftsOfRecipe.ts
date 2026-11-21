import { useProductionOrders } from "@/modules/maker/hooks/useProduction";

/**
 * How many open drafts read a BOM when they close (null while unknown). A draft takes its
 * ingredients and yield from the BOM at that moment, so an edit to the BOM
 * changes each of them; the confirmations of such edits say how many.
 */
export function useOpenDraftsOfRecipe(
  recipe: { id: string; output_template_id: string },
  /** Read only while a confirmation that quotes the count is open. */
  enabled: boolean,
): number | null {
  const { data, isError } = useProductionOrders(
    {
      status: "DRAFT",
      output_template_id: recipe.output_template_id,
      limit: 200,
    },
    { enabled },
  );
  // Null is "not known": the read has not answered or failed, and the
  // confirmation then states nothing about drafts rather than none.
  if (isError || !data) return null;
  return data.items.filter((order) => order.recipe_id === recipe.id).length;
}
