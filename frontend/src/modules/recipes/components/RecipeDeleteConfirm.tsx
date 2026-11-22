import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { formatDateMedium } from "@/utils/formatters";
import { useRecipePlannedMeals } from "../hooks/useRecipes";
import type { RecipePlannedMeal } from "../types/mealplans";

/** Meals named in the sentence before the rest are counted. */
const MEALS_NAMED = 5;

interface RecipeDeleteConfirmProps {
  /** The recipe asked about; the dialog is closed while it is null. */
  recipeId: string | null;
  name: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Asks before a recipe goes. Its meal-plan entries go with it, so the question
 * names the plans, days and meals it will empty; while that is unknown (the
 * read is on its way or failed) it says only that plans lose such meals.
 */
export function RecipeDeleteConfirm({
  recipeId,
  name,
  onConfirm,
  onCancel,
}: RecipeDeleteConfirmProps) {
  const { t } = useTranslation("recipes");
  const planned = useRecipePlannedMeals(recipeId ?? undefined, !!recipeId);
  const meals: RecipePlannedMeal[] | undefined = planned.data;

  const message = !meals
    ? t("actions.delete_confirm", { name })
    : meals.length === 0
      ? t("actions.delete_confirm_unplanned", { name })
      : t("actions.delete_confirm_planned", {
          name,
          meals: [
            ...meals
              .slice(0, MEALS_NAMED)
              .map((meal) =>
                [
                  meal.plan_name,
                  formatDateMedium(meal.date),
                  t(`meal_planner.slots.${meal.slot.toLowerCase()}`),
                ]
                  .filter(Boolean)
                  .join(", "),
              ),
            ...(meals.length > MEALS_NAMED
              ? [
                  t("actions.delete_planned_more", {
                    count: meals.length - MEALS_NAMED,
                  }),
                ]
              : []),
          ].join("; "),
        });

  return (
    <ConfirmDialog
      open={Boolean(recipeId)}
      variant="danger"
      title={t("actions.delete")}
      message={message}
      confirmLabel={t("actions.delete")}
      cancelLabel={t("common:form.cancel")}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
