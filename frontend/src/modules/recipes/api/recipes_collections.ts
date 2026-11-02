import { api, getEveryPage } from "@/lib/api/client";
import type {
  RecipeCollection,
  RecipeCollectionCreate,
} from "@/modules/recipes/types/core";

export const recipesCollectionsApi = {
  listCollections: async (): Promise<RecipeCollection[]> => {
    return getEveryPage<RecipeCollection>("/recipes/collections");
  },

  createCollection: async (
    data: RecipeCollectionCreate,
  ): Promise<RecipeCollection> => {
    const response = await api.post<RecipeCollection>(
      "/recipes/collections",
      data,
    );
    return response.data;
  },

  updateCollection: async (
    id: string,
    data: Partial<RecipeCollectionCreate>,
  ): Promise<RecipeCollection> => {
    const response = await api.put<RecipeCollection>(
      `/recipes/collections/${id}`,
      data,
    );
    return response.data;
  },

  deleteCollection: async (id: string): Promise<void> => {
    await api.delete(`/recipes/collections/${id}`);
  },

  addRecipeToCollection: async (
    collectionId: string,
    recipeId: string,
  ): Promise<{ collection_id: string; recipe_id: string }> => {
    const response = await api.post(
      `/recipes/collections/${collectionId}/recipes`,
      { recipe_id: recipeId },
    );
    return response.data;
  },

  removeRecipeFromCollection: async (
    collectionId: string,
    recipeId: string,
  ): Promise<void> => {
    await api.delete(
      `/recipes/collections/${collectionId}/recipes/${recipeId}`,
    );
  },
};
