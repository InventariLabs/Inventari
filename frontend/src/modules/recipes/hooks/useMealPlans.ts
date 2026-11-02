import { useAppMutation } from "@/lib/api/mutationFactory";
import { recipesApi } from "@/modules/recipes/api/recipes";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { invalidation } from "@/lib/api/invalidation";
import { useQueryClient } from "@tanstack/react-query";
import type {
  MealPlan,
  MealPlanCreate,
  MealPlanUpdateInput,
  MealPlanEntryCreate,
  MealPlanEntryUpdate,
  CopyPlanRequest,
  ShoppingExclusionCreate,
} from "@/modules/recipes/types/mealplans";

export function useMealPlans(params?: {
  start_date?: string;
  end_date?: string;
  offset?: number;
  limit?: number;
}) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.mealPlans.all(params),
    queryFn: () => recipesApi.listMealPlans(params),
  });
}

export function useMealPlan(id: string | undefined) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.mealPlans.detail(id!),
    queryFn: () => recipesApi.getMealPlan(id!),
    extraEnabled: !!id,
  });
}

export function useCreateMealPlan() {
  return useAppMutation(
    (data: MealPlanCreate) => recipesApi.createMealPlan(data),
    (qc) => {
      invalidation.mealPlans(qc);
    },
  );
}

export function useUpdateMealPlan() {
  return useAppMutation(
    ({ id, data }: { id: string; data: MealPlanUpdateInput }) =>
      recipesApi.updateMealPlan(id, data),
    (qc, _result, { id }) => {
      invalidation.mealPlans(qc, id);
    },
  );
}

export function useDeleteMealPlan() {
  return useAppMutation(
    (id: string) => recipesApi.deleteMealPlan(id),
    (qc) => {
      invalidation.mealPlans(qc);
    },
  );
}

export function useAddMealPlanEntry() {
  return useAppMutation(
    ({ planId, data }: { planId: string; data: MealPlanEntryCreate }) =>
      recipesApi.addMealPlanEntry(planId, data),
    (qc, _result, { planId }) => {
      invalidation.mealPlans(qc, planId);
    },
  );
}

export function useDeleteMealPlanEntry() {
  return useAppMutation(
    ({ planId, entryId }: { planId: string; entryId: string }) =>
      recipesApi.deleteMealPlanEntry(planId, entryId),
    (qc, _result, { planId }) => {
      invalidation.mealPlans(qc, planId);
    },
  );
}

export function useUpdateMealPlanEntry() {
  const queryClient = useQueryClient();
  return useAppMutation(
    ({
      planId,
      entryId,
      data,
    }: {
      planId: string;
      entryId: string;
      data: MealPlanEntryUpdate;
    }) => recipesApi.updateMealPlanEntry(planId, entryId, data),
    (qc, _result, { planId }) => {
      invalidation.mealPlans(qc, planId);
    },
    {
      // Optimistic move: update the cache immediately, roll back on error.
      onMutate: async ({ planId, entryId, data }) => {
        const detailKey = queryKeys.mealPlans.detail(planId);
        await queryClient.cancelQueries({ queryKey: detailKey });
        const previous = queryClient.getQueryData<MealPlan>(detailKey);
        if (previous) {
          queryClient.setQueryData<MealPlan>(detailKey, {
            ...previous,
            entries: previous.entries.map((entry) =>
              entry.id === entryId
                ? {
                    ...entry,
                    date: data.date ?? entry.date,
                    slot: data.slot ?? entry.slot,
                    order: data.order ?? entry.order,
                    servings: data.servings ?? entry.servings,
                    notes: data.notes ?? entry.notes,
                  }
                : entry,
            ),
          });
        }
        return { previous };
      },
      onError: (_err, vars, context) => {
        const previous = (
          context as { previous?: MealPlan | undefined } | undefined
        )?.previous;
        if (previous) {
          queryClient.setQueryData(
            queryKeys.mealPlans.detail(vars.planId),
            previous,
          );
        }
      },
    },
  );
}

export function useGenerateMealPlanShoppingList() {
  return useAppMutation(
    (planId: string) => recipesApi.generateMealPlanShoppingList(planId),
    (qc, _result, planId) => {
      invalidation.mealPlans(qc, planId);
      // The generated list shows up in the shopping list view.
      invalidation.shoppingLists(qc);
    },
  );
}

export function useCopyPlanToWeek() {
  return useAppMutation(
    ({ planId, data }: { planId: string; data: CopyPlanRequest }) =>
      recipesApi.copyMealPlanToWeek(planId, data),
    (qc, _result, { planId }) => {
      invalidation.mealPlans(qc, planId);
    },
  );
}

export function useShoppingExclusions() {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.mealPlans.exclusions,
    queryFn: () => recipesApi.getShoppingExclusions(),
  });
}

export function useCreateShoppingExclusion() {
  return useAppMutation(
    (data: ShoppingExclusionCreate) => recipesApi.createShoppingExclusion(data),
    (qc) => {
      invalidation.mealPlans(qc);
      // The availability payload carries `excluded`, which the "Add
      // missing" door reads: a fresh exclusion changes the door's answer
      // on any open recipe.
      invalidation.recipeAvailability(qc);
    },
  );
}

export function useDeleteShoppingExclusion() {
  return useAppMutation(
    (id: string) => recipesApi.deleteShoppingExclusion(id),
    (qc) => {
      invalidation.mealPlans(qc);
      invalidation.recipeAvailability(qc);
    },
  );
}
