import type { TFunction } from "i18next";
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
  // Null is "not known": the read has not answered or failed.
  if (isError || !data) return null;
  return data.items.filter((order) => order.recipe_id === recipe.id).length;
}

/**
 * What a confirmation says about the open drafts: their count, nothing when
 * there are none, and that the count is unknown when the read has not
 * answered — an unknown count is not "no drafts".
 */
export function openDraftsSentence(
  t: TFunction,
  openDrafts: number | null,
): string | null {
  if (openDrafts === null) return t("maker:composition.openDraftsUnknown");
  if (openDrafts === 0) return null;
  return t("maker:composition.openDraftsChange", { number: openDrafts });
}
