import { recipesApi } from "@/modules/recipes/api/recipes";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import type { MealSlot } from "@/modules/recipes/types/mealplans";

export function useMealPlanSuggestions(params: {
  date: string;
  slot: MealSlot;
  count?: number;
  plan_id?: string;
}) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.mealPlans.suggestions(params),
    queryFn: () => recipesApi.getMealPlanSuggestions(params),
    extraEnabled: !!params.date && !!params.slot,
  });
}
