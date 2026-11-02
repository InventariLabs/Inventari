import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import RecipeIngredientRow from "./RecipeIngredientRow";
import type { IngredientDraft } from "./RecipeIngredientRow";
import { useIngredientStockUnits } from "@/modules/recipes/hooks/useIngredientStockUnits";

export type { IngredientDraft } from "./RecipeIngredientRow";

interface Props {
  ingredients: IngredientDraft[];
  errors: Record<string, string>;
  onUpdate: (
    key: number,
    field: keyof IngredientDraft,
    value: IngredientDraft[keyof IngredientDraft],
  ) => void;
  onRemove: (key: number) => void;
  onAdd: () => void;
  onNameBlur: (ing: IngredientDraft) => void;
}

export default function RecipeIngredientsSection({
  ingredients,
  errors,
  onUpdate,
  onRemove,
  onAdd,
  onNameBlur,
}: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  // Each linked ingredient's stock unit, so a row offers only the units the
  // maker can convert into it. One query for the whole sheet.
  const {
    stockUnits,
    isError: stockUnitsFailed,
    error: stockUnitsError,
    refetch: refetchStockUnits,
  } = useIngredientStockUnits(
    ingredients.map((ing) => ing.template_id ?? null),
  );

  return (
    <div>
      {/* h3: the sheet's own SheetTitle is the h2 above it (§2.11). */}
      <h3 className="text-sm font-semibold text-on-secondary mb-2">
        {t("form.ingredients_section")}
      </h3>
      {stockUnitsFailed && (
        <div className="mb-2">
          <InlineQueryError
            error={stockUnitsError}
            onRetry={refetchStockUnits}
          />
        </div>
      )}
      <div className="space-y-2">
        {ingredients.map((ing, idx) => (
          <RecipeIngredientRow
            key={ing._key}
            ing={ing}
            idx={idx}
            errors={errors}
            onUpdate={onUpdate}
            onRemove={onRemove}
            onNameBlur={onNameBlur}
            stockUnit={
              ing.template_id ? stockUnits[ing.template_id] : undefined
            }
          />
        ))}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onAdd}
        className="mt-2 gap-1"
      >
        <Plus size={16} />
        {t("form.add_ingredient")}
      </Button>
    </div>
  );
}
