import { useTranslation } from "react-i18next";
import { UnitCostValue } from "@/modules/maker/components/UnitCostValue";
import type { RecipeCatalogItem } from "@/modules/maker/types/maker";

interface RecipeUnitCostProps {
  recipe: RecipeCatalogItem;
  /** `inline` (cards) puts the label beside the figure; `stacked` (table
   * cells) puts it under it. */
  layout?: "inline" | "stacked";
}

/**
 * The recipe's unit cost with the label that says which of the two
 * quantities it is.
 *
 * The card grew the label in one view while the table kept printing the
 * bare run figure under a heading that also covered the estimate — the
 * same two quantities met the same word in two views of one page. One
 * component, one rule: a run's figure reads "after last run", a never-run
 * recipe reads "estimated", and the dash survives only where there is
 * nothing to compute from.
 */
export function RecipeUnitCost({
  recipe,
  layout = "inline",
}: RecipeUnitCostProps) {
  const { t } = useTranslation("maker");

  const label =
    recipe.unit_cost != null
      ? t("catalog.unitCostAfterRun")
      : recipe.estimated_unit_cost != null
        ? t("catalog.unitCostEstimated")
        : t("catalog.unitCost");
  const value = (
    <span className="font-medium text-on tabular-nums">
      {recipe.unit_cost != null ? (
        <UnitCostValue
          value={recipe.unit_cost}
          uncosted={recipe.uncosted_ingredients}
        />
      ) : recipe.estimated_unit_cost != null ? (
        // An estimate is not a run: the unpriced note has to say so instead
        // of claiming an ingredient of "the last run" that never happened.
        <UnitCostValue
          value={recipe.estimated_unit_cost}
          uncosted={recipe.estimated_uncosted_ingredients ?? 0}
          note={t("catalog.estimateCostIncomplete", {
            count: recipe.estimated_uncosted_ingredients ?? 0,
          })}
        />
      ) : (
        <UnitCostValue value={null} uncosted={0} />
      )}
    </span>
  );

  if (layout === "stacked") {
    return (
      <span className="inline-flex flex-col items-end">
        {value}
        <span className="text-[10px] font-normal text-on-muted">{label}</span>
      </span>
    );
  }
  return (
    <>
      <span className="text-on-muted">{label}</span> {value}
    </>
  );
}
