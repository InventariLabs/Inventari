import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, DollarSign } from "lucide-react";
import { useRecipeCost } from "../hooks/useRecipes";
import { Button } from "@/components/ui/Button";
import { CollapsibleDetailSection } from "./CollapsibleDetailSection";
import { formatMoney } from "@/utils/formatters";

interface RecipeCostSectionProps {
  recipeId: string;
  activeServings: number;
  /** opens the recipe editor so missing ingredient prices can be filled in. */
  onEditRecipe?: () => void;
}

export default function RecipeCostSection({
  recipeId,
  activeServings,
  onEditRecipe,
}: RecipeCostSectionProps) {
  const { t } = useTranslation("recipes");
  const [open, setOpen] = useState(false);

  // The page asks for this same cost anyway, so the answer is shared; it is
  // what tells the section whether the organization has a cost at all.
  const costQuery = useRecipeCost(recipeId, activeServings);
  const data = costQuery.data;

  if (data?.enabled === false) return null;

  return (
    <CollapsibleDetailSection
      title={t("cost.title")}
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <>
        {costQuery.isLoading && (
          <div className="py-4 flex justify-center">
            <Loader2 size={18} className="animate-spin text-on-muted" />
          </div>
        )}

        {data && data.estimated_cost == null && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-on-muted">{t("cost.no_data")}</p>
            {onEditRecipe && (
              <Button
                variant="ghost"
                size="contentSm"
                onClick={onEditRecipe}
                className="text-primary-600 hover:text-primary-700 px-0 text-xs min-h-11 md:min-h-0 min-w-11 md:min-w-0"
              >
                {t("common:form.edit")}
              </Button>
            )}
          </div>
        )}

        {data && data.estimated_cost != null && (
          <div className="space-y-3">
            {/* Total */}
            <div className="flex items-center gap-2">
              <DollarSign size={16} className="text-accent-600" />
              <span className="text-lg font-semibold text-on">
                {formatMoney(data.estimated_cost, data.currency ?? "")}
              </span>
              <span className="text-xs text-on-muted">
                {t("cost.per_servings", { servings: data.servings })}
              </span>
            </div>

            {/* Coverage */}
            <p className="text-xs text-on-secondary">
              {t("cost.coverage", {
                pct: Math.round(data.cost_coverage * 100),
              })}
              {data.mixed_currencies && (
                <span className="ml-2 text-amber-600">
                  · {t("cost.mixed_currencies")}
                </span>
              )}
            </p>

            {/* Missing */}
            {data.missing_cost_ingredients.length > 0 && (
              <p className="text-xs text-on-muted">
                {t("cost.missing_prefix")}{" "}
                {data.missing_cost_ingredients.join(", ")}
              </p>
            )}

            {/* Per-ingredient breakdown */}
            <div className="divide-y divide-border border border-border rounded-xl overflow-hidden text-xs">
              {data.ingredients.map((ing) => (
                <div
                  key={ing.ingredient_name}
                  className="flex items-center justify-between px-3 py-2"
                >
                  <span className="text-on-secondary">
                    {ing.ingredient_name}
                  </span>
                  {ing.estimated_cost != null ? (
                    <span className="font-medium text-on">
                      {formatMoney(ing.estimated_cost, ing.currency ?? "")}
                    </span>
                  ) : (
                    <span className="text-on-muted">—</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </>
    </CollapsibleDetailSection>
  );
}
