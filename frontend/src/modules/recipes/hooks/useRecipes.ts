import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { recipesApi } from "@/modules/recipes/api/recipes";
import { invalidation } from "@/lib/api/invalidation";
import type {
  RecipeCreateInput,
  RecipeUpdate,
  RecipeCollectionCreate,
} from "@/modules/recipes/types/core";
import type {
  TagMergeRequest,
  RecipeImportRequest,
} from "@/modules/recipes/types/nutrition";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

export function useRecipes(params?: {
  search?: string;
  tags?: string;
  is_favorite?: boolean;
  collection_id?: string;
  skip?: number;
  limit?: number;
  sort?: string;
}) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.recipes.all(params),
    queryFn: () => recipesApi.list(params),
  });
}

export function useAvailableRecipes(params?: {
  min_match?: number;
  tags?: string;
}) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.recipes.available(params),
    queryFn: () => recipesApi.getAvailable(params),
  });
}

export function useRecipe(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.recipes.detail(id!),
    queryFn: () => recipesApi.getById(id!),
    enabled: !!id,
  });
}

export function useRecipeAvailability(
  id: string | undefined,
  servings?: number,
) {
  return useQuery({
    queryKey: queryKeys.recipes.availability(id!, servings!),
    queryFn: () => recipesApi.getAvailability(id!, servings),
    enabled: !!id,
  });
}

export function useCreateRecipe() {
  return useAppMutation(
    (data: RecipeCreateInput) => recipesApi.create(data),
    (qc) => {
      invalidation.recipes(qc);
    },
  );
}

export function useDuplicateRecipe() {
  return useAppMutation(
    (id: string) => recipesApi.duplicate(id),
    (qc) => {
      invalidation.recipes(qc);
    },
  );
}

export function useBulkDeleteRecipes() {
  return useAppMutation(
    (recipeIds: string[]) => recipesApi.bulkDelete(recipeIds),
    (qc) => {
      invalidation.recipes(qc);
    },
  );
}

export function useBulkTagRecipes() {
  return useAppMutation(
    ({ recipeIds, tags }: { recipeIds: string[]; tags: string[] }) =>
      recipesApi.bulkTag(recipeIds, tags),
    (qc) => {
      invalidation.recipes(qc);
    },
  );
}

// ── Recipe collections ──────────────────────────────────────────────────────

export function useRecipeCollections() {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.recipes.collections,
    queryFn: () => recipesApi.listCollections(),
  });
}

export function useCreateRecipeCollection() {
  return useAppMutation(
    (data: RecipeCollectionCreate) => recipesApi.createCollection(data),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.collections });
    },
  );
}

export function useUpdateRecipeCollection() {
  return useAppMutation(
    ({ id, data }: { id: string; data: Partial<RecipeCollectionCreate> }) =>
      recipesApi.updateCollection(id, data),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.collections });
    },
  );
}

export function useDeleteRecipeCollection() {
  return useAppMutation(
    (id: string) => recipesApi.deleteCollection(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.collections });
    },
  );
}

export function useAddRecipeToCollection() {
  return useAppMutation(
    ({ collectionId, recipeId }: { collectionId: string; recipeId: string }) =>
      recipesApi.addRecipeToCollection(collectionId, recipeId),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.collections });
      qc.invalidateQueries({ queryKey: queryKeys.recipes.all() });
      // The chips count the collection the reader is in, so a membership
      // change moves them too — without this the empty state's picker left
      // the counts it had cached before the first recipe joined.
      qc.invalidateQueries({ queryKey: queryKeys.recipes.tags });
    },
  );
}

export function useUpdateRecipe() {
  return useAppMutation(
    ({ id, data }: { id: string; data: RecipeUpdate }) =>
      recipesApi.update(id, data),
    (qc, _result, { id }) => {
      invalidation.recipes(qc, id);
    },
  );
}

export function useDeleteRecipe() {
  return useAppMutation(
    (id: string) => recipesApi.delete(id),
    (qc) => {
      invalidation.recipes(qc);
    },
  );
}

export function useLinkIngredientTemplate(recipeId: string) {
  return useAppMutation(
    ({
      ingredientId,
      templateId,
    }: {
      ingredientId: string;
      templateId: string;
    }) => recipesApi.linkIngredientTemplate(recipeId, ingredientId, templateId),
    (qc) => {
      invalidation.recipes(qc, recipeId);
    },
  );
}

export function useRecipeNutrition(id: string | undefined, servings?: number) {
  return useQuery({
    queryKey: queryKeys.recipes.nutrition(id!, servings!),
    queryFn: () => recipesApi.getNutrition(id!, servings),
    enabled: !!id,
  });
}

export function useRecipeHistory(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.recipes.history(id!),
    queryFn: () => recipesApi.getHistory(id!),
    enabled: !!id,
  });
}

export function useCreateCookingHistory(recipeId: string) {
  return useAppMutation(
    (options?: { servings?: number; sessionId?: string }) =>
      recipesApi.recordCooking(recipeId, options),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.history(recipeId) });
    },
  );
}

export function usePatchCookingHistory(recipeId: string) {
  return useAppMutation(
    ({
      sessionId,
      data,
    }: {
      sessionId: string;
      data: { notes?: string | null; rating?: number | null };
    }) => recipesApi.patchHistory(recipeId, sessionId, data),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.history(recipeId) });
    },
  );
}

/**
 * The active shopping list's id, under the active-list key so every write to
 * a list (`invalidation.shoppingLists`) refreshes it too.
 */
export function useActiveShoppingListId() {
  return useModuleQuery("shopping_lists", {
    queryKey: [...queryKeys.shoppingLists.active, "id"],
    queryFn: () => recipesApi.getActiveShoppingListId(),
    staleTime: 30000,
  });
}

export function useAddToShoppingList(recipeId: string) {
  return useAppMutation(
    (data: { shopping_list_id?: string; servings?: number }) =>
      recipesApi.addToShoppingList(recipeId, data),
    (qc) => {
      // The shopping list view must refresh after items are added.
      invalidation.shoppingLists(qc);
    },
  );
}

export function useUploadRecipeImage() {
  return useAppMutation(
    ({ id, file }: { id: string; file: File }) =>
      recipesApi.uploadImage(id, file),
    (qc, _result, { id }) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.detail(id) });
    },
  );
}

export function useDeleteRecipeImage() {
  return useAppMutation(
    (id: string) => recipesApi.deleteImage(id),
    (qc, _result, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.detail(id) });
    },
  );
}

export function useRecipeCost(id: string | undefined, servings?: number) {
  return useQuery({
    queryKey: queryKeys.recipes.cost(id!, servings),
    queryFn: () => recipesApi.getCost(id!, servings),
    enabled: !!id,
  });
}

export interface RecipeTagFilters {
  search?: string;
  tags?: string;
  is_favorite?: boolean;
  collection_id?: string;
}

export function useRecipeTags(filters: RecipeTagFilters = {}) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.recipes.tagsFor(filters),
    queryFn: () => recipesApi.getTags(filters),
  });
}

export function useSetTagColor() {
  return useAppMutation(
    ({ name, color }: { name: string; color: string | null }) =>
      recipesApi.setTagColor(name, color),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.recipes.tags });
    },
  );
}

export function useMergeTags() {
  return useAppMutation(
    (req: TagMergeRequest) => recipesApi.mergeTags(req),
    (qc) => {
      invalidation.recipes(qc);
      qc.invalidateQueries({ queryKey: queryKeys.recipes.tags });
    },
  );
}

export function useDeleteTag() {
  return useAppMutation(
    (name: string) => recipesApi.deleteTag(name),
    (qc) => {
      invalidation.recipes(qc);
      qc.invalidateQueries({ queryKey: queryKeys.recipes.tags });
    },
  );
}

export function usePreviewImport() {
  return useMutation({
    mutationFn: (req: RecipeImportRequest) => recipesApi.previewImport(req),
  });
}

export function useExportRecipe() {
  return useMutation({
    mutationFn: ({
      id,
      format,
    }: {
      id: string;
      format: "json" | "schema_org";
    }) => recipesApi.exportRecipe(id, format),
  });
}

/**
 * Mark one recipe as favourite wherever it is cached, whatever shape it is in.
 *
 * `["recipes"]` is a prefix, and two different caches sit under it: the list
 * holds `{ items, total }` and the "what can I cook" tab holds a plain array.
 * The optimistic update assumed the array everywhere and called `old.map` on
 * the object — a TypeError inside `onMutate`, which TanStack v5 treats as the
 * mutation having failed. It went straight to `onError` **without calling
 * `mutationFn`**, so every click on the star showed "could not save" and the
 * request never left the browser.
 *
 * Anything else under the prefix is handed back untouched: guessing at a
 * shape is what broke this in the first place.
 */
function markFavorite<T>(cached: T, recipeId: string, newValue: boolean): T {
  const mark = (row: { id: string }) =>
    row.id === recipeId ? { ...row, is_favorite: newValue } : row;

  if (Array.isArray(cached)) {
    return cached.map(mark) as T;
  }
  if (cached && typeof cached === "object" && "items" in cached) {
    const page = cached as { items: unknown };
    if (Array.isArray(page.items)) {
      return { ...cached, items: page.items.map(mark) } as T;
    }
  }
  return cached;
}

export function useToggleRecipeFavorite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      recipeId,
      newValue,
    }: {
      recipeId: string;
      newValue: boolean;
    }) => recipesApi.update(recipeId, { is_favorite: newValue }),
    onMutate: async ({ recipeId, newValue }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.recipes.all() });
      const previousData = queryClient.getQueriesData({
        queryKey: queryKeys.recipes.all(),
      });
      queryClient.setQueriesData(
        { queryKey: queryKeys.recipes.all() },
        (old: unknown) =>
          old === undefined ? old : markFavorite(old, recipeId, newValue),
      );
      return { previousData };
    },
    onError: (_err, _variables, context) => {
      if (context?.previousData) {
        for (const [key, data] of context.previousData) {
          queryClient.setQueryData(key, data);
        }
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.recipes.all() });
      // The favorites tab counts its chips within favorites, so the flip
      // moves those counts too.
      queryClient.invalidateQueries({ queryKey: queryKeys.recipes.tags });
    },
  });
}
