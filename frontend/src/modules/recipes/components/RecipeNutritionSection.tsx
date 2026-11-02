import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { useRecipeNutrition } from "../hooks/useRecipes";
import NutritionCard from "./NutritionCard";
import { Button } from "@/components/ui/Button";
import { CollapsibleDetailSection } from "./CollapsibleDetailSection";

interface RecipeNutritionSectionProps {
  recipeId: string;
  activeServings: number;
  /** opens the recipe editor so missing per-ingredient data can be filled in. */
  onEditRecipe?: () => void;
}

export default function RecipeNutritionSection({
  recipeId,
  activeServings,
  onEditRecipe,
}: RecipeNutritionSectionProps) {
  const { t } = useTranslation("recipes");
  const [showNutrition, setShowNutrition] = useState(false);

  const nutritionQuery = useRecipeNutrition(
    showNutrition ? recipeId : undefined,
    activeServings,
  );

  return (
    <CollapsibleDetailSection
      title={t("nutrition.title")}
      open={showNutrition}
      onToggle={() => setShowNutrition((v) => !v)}
      padded={false}
    >
      <>
        {nutritionQuery.isLoading && (
          <div className="py-4 flex justify-center">
            <Loader2 size={18} className="animate-spin text-on-muted" />
          </div>
        )}
        {nutritionQuery.data && (
          <div className="px-5 pb-4">
            <NutritionCard
              data={nutritionQuery.data}
              servings={activeServings}
              onEditRecipe={onEditRecipe}
            />
          </div>
        )}
        {!nutritionQuery.isLoading &&
          !nutritionQuery.data &&
          nutritionQuery.isFetched && (
            <div className="flex flex-col items-start gap-2 px-5 pb-4">
              <p className="text-sm text-on-muted">{t("nutrition.no_data")}</p>
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
      </>
    </CollapsibleDetailSection>
  );
}
