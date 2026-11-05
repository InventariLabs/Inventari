import { prepareImageUpload } from "@/lib/imageUtils";
import { api, getEveryPage } from "@/lib/api/client";
import { IMAGE_UPLOAD_MAX_BYTES, assertFileSize } from "@/utils/fileValidation";
import type {
  Recipe,
  RecipeList,
  RecipeCreateInput,
  RecipeUpdate,
  RecipeAvailability,
  PickingStartResponse,
  PickingScanResponse,
  UndoPickResponse,
} from "@/modules/recipes/types/core";
import type {
  RecipeNutrition,
  CookingHistoryItem,
  RecipeCost,
  RecipeTagItem,
  TagMergeRequest,
  TagMergeResponse,
  RecipeImportRequest,
  RecipeImportPreview,
} from "@/modules/recipes/types/nutrition";

export const recipesCoreApi = {
  list: async (params?: {
    search?: string;
    tags?: string;
    is_favorite?: boolean;
    collection_id?: string;
    skip?: number;
    limit?: number;
    sort?: string;
  }): Promise<{ items: RecipeList[]; total: number }> => {
    const response = await api.get<{ items: RecipeList[]; total: number }>(
      "/recipes",
      { params },
    );
    return response.data;
  },

  getAvailable: async (params?: {
    min_match?: number;
    servings?: number;
    tags?: string;
  }): Promise<
    (RecipeList & { match_percentage: number; missing_names: string[] })[]
  > => {
    return getEveryPage<
      RecipeList & { match_percentage: number; missing_names: string[] }
    >("/recipes/available", params);
  },

  getById: async (id: string): Promise<Recipe> => {
    const response = await api.get<Recipe>(`/recipes/${id}`);
    return response.data;
  },

  create: async (data: RecipeCreateInput): Promise<Recipe> => {
    const response = await api.post<Recipe>("/recipes", data);
    return response.data;
  },

  duplicate: async (id: string): Promise<Recipe> => {
    const response = await api.post<Recipe>(`/recipes/${id}/duplicate`);
    return response.data;
  },

  bulkDelete: async (recipeIds: string[]): Promise<{ deleted: number }> => {
    const response = await api.post<{ deleted: number }>(
      "/recipes/bulk-delete",
      { recipe_ids: recipeIds },
    );
    return response.data;
  },

  bulkTag: async (
    recipeIds: string[],
    tags: string[],
  ): Promise<{ updated: number }> => {
    const response = await api.post<{ updated: number }>("/recipes/bulk-tag", {
      recipe_ids: recipeIds,
      tags,
    });
    return response.data;
  },

  update: async (id: string, data: RecipeUpdate): Promise<Recipe> => {
    const response = await api.put<Recipe>(`/recipes/${id}`, data);
    return response.data;
  },

  linkIngredientTemplate: async (
    recipeId: string,
    ingredientId: string,
    templateId: string,
  ): Promise<Recipe> => {
    const response = await api.post<Recipe>(
      `/recipes/${recipeId}/ingredients/${ingredientId}/link-template`,
      { template_id: templateId },
    );
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/recipes/${id}`);
  },

  getAvailability: async (
    id: string,
    servings?: number,
  ): Promise<RecipeAvailability> => {
    const response = await api.get<RecipeAvailability>(
      `/recipes/${id}/availability`,
      {
        params: servings ? { servings } : undefined,
      },
    );
    return response.data;
  },

  startPicking: async (
    id: string,
    servings: number = 1,
    mealPlanEntryId?: string,
  ): Promise<PickingStartResponse> => {
    const response = await api.post<PickingStartResponse>(
      `/recipes/${id}/picking/start`,
      { servings, meal_plan_entry_id: mealPlanEntryId },
    );
    return response.data;
  },

  readPicking: async (
    recipeId: string,
    sessionId: string,
  ): Promise<PickingStartResponse> => {
    const response = await api.get<PickingStartResponse>(
      `/recipes/${recipeId}/picking/${sessionId}`,
    );
    return response.data;
  },

  scanPicking: async (
    recipeId: string,
    sessionId: string,
    data: { barcode?: string; item_id?: string; from_checklist?: boolean },
  ): Promise<PickingScanResponse> => {
    const response = await api.post<PickingScanResponse>(
      `/recipes/${recipeId}/picking/${sessionId}/scan`,
      data,
    );
    return response.data;
  },

  completePicking: async (
    recipeId: string,
    sessionId: string,
  ): Promise<unknown> => {
    const response = await api.post(
      `/recipes/${recipeId}/picking/${sessionId}/complete`,
    );
    return response.data;
  },

  cancelPicking: async (recipeId: string, sessionId: string): Promise<void> => {
    await api.delete(`/recipes/${recipeId}/picking/${sessionId}`);
  },

  undoPick: async (
    recipeId: string,
    sessionId: string,
    ingredientId: string,
  ): Promise<UndoPickResponse> => {
    const response = await api.post<UndoPickResponse>(
      `/recipes/${recipeId}/picking/${sessionId}/undo`,
      { ingredient_id: ingredientId },
    );
    return response.data;
  },

  getNutrition: async (
    id: string,
    servings?: number,
  ): Promise<RecipeNutrition> => {
    const response = await api.get<RecipeNutrition>(
      `/recipes/${id}/nutrition`,
      {
        params: servings ? { servings } : undefined,
      },
    );
    return response.data;
  },

  /**
   * The list "add to shopping list" puts the ingredients on: the newest
   * active one, or ``null`` when there is none and the server is to make the
   * first. Read over the shopping lists' HTTP route — that module is optional
   * here, and an import of its files cannot be.
   */
  getActiveShoppingListId: async (): Promise<string | null> => {
    const response = await api.get<{ items: { id: string }[] }>(
      "/shopping-lists",
      { params: { active_only: true, limit: 1 } },
    );
    return response.data.items[0]?.id ?? null;
  },

  addToShoppingList: async (
    id: string,
    data: { shopping_list_id?: string; servings?: number },
  ): Promise<{
    shopping_list_id: string;
    added_count: number;
    /** Missing goods left off because the list already carries them. */
    already_listed_count?: number;
    list_name?: string | null;
    /** Lines written that another open list still asks for too. */
    on_other_lists?: { name: string; list_id: string; list_name: string }[];
  }> => {
    const response = await api.post(
      `/recipes/${id}/add-to-shopping-list`,
      data,
    );
    return response.data;
  },

  getHistory: async (
    id: string,
    params?: { limit?: number; offset?: number },
  ): Promise<CookingHistoryItem[]> => {
    const response = await api.get<{ items: CookingHistoryItem[] }>(
      `/recipes/${id}/history`,
      { params },
    );
    return response.data.items;
  },

  recordCooking: async (
    recipeId: string,
    options?: { servings?: number; sessionId?: string },
  ): Promise<CookingHistoryItem> => {
    const response = await api.post<CookingHistoryItem>(
      `/recipes/${recipeId}/history`,
      {
        ...(options?.servings ? { servings: options.servings } : {}),
        // The cook that follows a picking run is the same dinner: naming the
        // session closes that entry instead of opening a second one beside it.
        ...(options?.sessionId ? { session_id: options.sessionId } : {}),
      },
    );
    return response.data;
  },

  patchHistory: async (
    recipeId: string,
    sessionId: string,
    data: { notes?: string | null; rating?: number | null },
  ): Promise<CookingHistoryItem> => {
    const response = await api.patch<CookingHistoryItem>(
      `/recipes/${recipeId}/history/${sessionId}`,
      data,
    );
    return response.data;
  },

  uploadImage: async (
    id: string,
    file: File,
  ): Promise<{ image_url: string }> => {
    const image = await prepareImageUpload(file);
    assertFileSize(image, IMAGE_UPLOAD_MAX_BYTES);
    const form = new FormData();
    form.append("image", image);
    const response = await api.post<{ image_url: string }>(
      `/recipes/${id}/image`,
      form,
    );
    return response.data;
  },

  deleteImage: async (id: string): Promise<void> => {
    await api.delete(`/recipes/${id}/image`);
  },

  getCost: async (id: string, servings?: number): Promise<RecipeCost> => {
    const response = await api.get<RecipeCost>(`/recipes/${id}/cost`, {
      params: servings ? { servings } : undefined,
    });
    return response.data;
  },

  getTags: async (params?: {
    search?: string;
    tags?: string;
    is_favorite?: boolean;
    collection_id?: string;
  }): Promise<RecipeTagItem[]> => {
    return getEveryPage<RecipeTagItem>("/recipes/tags", params);
  },

  setTagColor: async (
    name: string,
    color: string | null,
  ): Promise<{ name: string; color: string | null }> => {
    const response = await api.patch<{ name: string; color: string | null }>(
      `/recipes/tags/${encodeURIComponent(name)}/color`,
      { color },
    );
    return response.data;
  },

  deleteTag: async (
    name: string,
  ): Promise<{ name: string; updated_recipes: number }> => {
    const response = await api.delete<{
      name: string;
      updated_recipes: number;
    }>(`/recipes/tags/${encodeURIComponent(name)}`);
    return response.data;
  },

  mergeTags: async (req: TagMergeRequest): Promise<TagMergeResponse> => {
    const response = await api.post<TagMergeResponse>(
      "/recipes/tags/merge",
      req,
    );
    return response.data;
  },

  exportRecipe: async (
    id: string,
    format: "json" | "schema_org" = "json",
  ): Promise<Record<string, unknown>> => {
    const response = await api.get<Record<string, unknown>>(
      `/recipes/${id}/export`,
      { params: { format } },
    );
    return response.data;
  },

  previewImport: async (
    req: RecipeImportRequest,
  ): Promise<RecipeImportPreview> => {
    const response = await api.post<RecipeImportPreview>(
      "/recipes/import/preview",
      req,
    );
    return response.data;
  },
};
