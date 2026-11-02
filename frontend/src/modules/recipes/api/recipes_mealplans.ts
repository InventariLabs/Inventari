import { api, getEveryPage } from "@/lib/api/client";
import type {
  MealPlan,
  MealPlanListItem,
  MealPlanCreate,
  MealPlanUpdateInput,
  MealPlanEntry,
  MealPlanEntryCreate,
  MealPlanEntryUpdate,
  CopyPlanRequest,
  CopyPlanResponse,
  SuggestedRecipe,
  ShoppingListGenerationResult,
  ShoppingExclusion,
  ShoppingExclusionCreate,
  MealSlot,
} from "@/modules/recipes/types/mealplans";

export const recipesMealPlansApi = {
  listMealPlans: async (params?: {
    start_date?: string;
    end_date?: string;
    offset?: number;
    limit?: number;
  }): Promise<MealPlanListItem[]> => {
    const response = await api.get<{ items: MealPlanListItem[] }>(
      "/recipes/meal-plans",
      { params },
    );
    return response.data.items;
  },

  getMealPlan: async (id: string): Promise<MealPlan> => {
    const response = await api.get<MealPlan>(`/recipes/meal-plans/${id}`);
    return response.data;
  },

  createMealPlan: async (data: MealPlanCreate): Promise<MealPlan> => {
    const response = await api.post<MealPlan>("/recipes/meal-plans", data);
    return response.data;
  },

  updateMealPlan: async (
    id: string,
    data: MealPlanUpdateInput,
  ): Promise<MealPlan> => {
    const response = await api.put<MealPlan>(`/recipes/meal-plans/${id}`, data);
    return response.data;
  },

  deleteMealPlan: async (id: string): Promise<void> => {
    await api.delete(`/recipes/meal-plans/${id}`);
  },

  addMealPlanEntry: async (
    planId: string,
    data: MealPlanEntryCreate,
  ): Promise<MealPlanEntry> => {
    const response = await api.post<MealPlanEntry>(
      `/recipes/meal-plans/${planId}/entries`,
      data,
    );
    return response.data;
  },

  deleteMealPlanEntry: async (
    planId: string,
    entryId: string,
  ): Promise<void> => {
    await api.delete(`/recipes/meal-plans/${planId}/entries/${entryId}`);
  },

  updateMealPlanEntry: async (
    planId: string,
    entryId: string,
    data: MealPlanEntryUpdate,
  ): Promise<MealPlanEntry> => {
    const response = await api.put<MealPlanEntry>(
      `/recipes/meal-plans/${planId}/entries/${entryId}`,
      data,
    );
    return response.data;
  },

  getMealPlanSuggestions: async (params: {
    date: string;
    slot: MealSlot;
    count?: number;
    plan_id?: string;
  }): Promise<SuggestedRecipe[]> => {
    const response = await api.get<SuggestedRecipe[]>(
      "/recipes/meal-plans/suggestions",
      { params },
    );
    return response.data;
  },

  copyMealPlanToWeek: async (
    planId: string,
    data: CopyPlanRequest,
  ): Promise<CopyPlanResponse> => {
    const response = await api.post<CopyPlanResponse>(
      `/recipes/meal-plans/${planId}/copy-to`,
      data,
    );
    return response.data;
  },

  generateMealPlanShoppingList: async (
    planId: string,
  ): Promise<ShoppingListGenerationResult> => {
    const response = await api.post<ShoppingListGenerationResult>(
      `/recipes/meal-plans/${planId}/generate-shopping-list`,
    );
    return response.data;
  },

  getShoppingExclusions: async (): Promise<ShoppingExclusion[]> => {
    return getEveryPage<ShoppingExclusion>("/recipes/meal-plans/exclusions");
  },

  createShoppingExclusion: async (
    data: ShoppingExclusionCreate,
  ): Promise<ShoppingExclusion> => {
    const response = await api.post<ShoppingExclusion>(
      "/recipes/meal-plans/exclusions",
      data,
    );
    return response.data;
  },

  deleteShoppingExclusion: async (id: string): Promise<void> => {
    await api.delete(`/recipes/meal-plans/exclusions/${id}`);
  },
};
