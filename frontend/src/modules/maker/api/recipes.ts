import { api } from "@/lib/api/client";
import type {
  AvailabilityResponse,
  BomLine,
  MakerSettings,
  MakerSettingsUpdate,
  MakerRecipe,
  RecipeCatalogResponse,
  RecipeCostLine,
  RecipeCostLineCreateInput,
  RecipeCostLineUpdate,
  RecipeCreateInput,
  RecipeUpdate,
} from "@/modules/maker/types/maker";

export interface BomLineUpdate {
  qty_per_batch?: string;
  uom_id?: string | null;
  yield_loss_pct?: string;
  notes?: string | null;
}

export interface BomLineCreate {
  child_template_id: string;
  qty_per_batch: string;
  unit: string;
  uom_id?: string | null;
  yield_loss_pct?: string;
  notes?: string | null;
}

export const recipeApi = {
  catalog: async (
    search?: string,
    sort?: string,
    skip?: number,
    limit?: number,
  ): Promise<RecipeCatalogResponse> => {
    const response = await api.get<RecipeCatalogResponse>("/maker/recipes", {
      params: { search, sort, skip, limit },
    });
    return response.data;
  },

  get: async (recipeId: string): Promise<MakerRecipe> => {
    const response = await api.get<MakerRecipe>(`/maker/recipes/${recipeId}`);
    return response.data;
  },

  create: async (data: RecipeCreateInput): Promise<MakerRecipe> => {
    const response = await api.post<MakerRecipe>("/maker/recipes", data);
    return response.data;
  },

  update: async (
    recipeId: string,
    data: RecipeUpdate,
  ): Promise<MakerRecipe> => {
    const response = await api.patch<MakerRecipe>(
      `/maker/recipes/${recipeId}`,
      data,
    );
    return response.data;
  },

  delete: async (recipeId: string): Promise<void> => {
    await api.delete(`/maker/recipes/${recipeId}`);
  },

  addBomLine: async (
    recipeId: string,
    data: BomLineCreate,
  ): Promise<BomLine> => {
    const response = await api.post<BomLine>(
      `/maker/recipes/${recipeId}/bom-lines`,
      data,
    );
    return response.data;
  },

  deleteBomLine: async (recipeId: string, lineId: string): Promise<void> => {
    await api.delete(`/maker/recipes/${recipeId}/bom-lines/${lineId}`);
  },

  updateBomLine: async (
    recipeId: string,
    lineId: string,
    data: BomLineUpdate,
  ): Promise<BomLine> => {
    const response = await api.patch<BomLine>(
      `/maker/recipes/${recipeId}/bom-lines/${lineId}`,
      data,
    );
    return response.data;
  },

  createCostLine: async (
    recipeId: string,
    data: RecipeCostLineCreateInput,
  ): Promise<RecipeCostLine> => {
    const response = await api.post<RecipeCostLine>(
      `/maker/recipes/${recipeId}/cost-lines`,
      data,
    );
    return response.data;
  },

  updateCostLine: async (
    recipeId: string,
    lineId: string,
    data: RecipeCostLineUpdate,
  ): Promise<RecipeCostLine> => {
    const response = await api.patch<RecipeCostLine>(
      `/maker/recipes/${recipeId}/cost-lines/${lineId}`,
      data,
    );
    return response.data;
  },

  deleteCostLine: async (recipeId: string, lineId: string): Promise<void> => {
    await api.delete(`/maker/recipes/${recipeId}/cost-lines/${lineId}`);
  },

  getSettings: async (): Promise<MakerSettings> => {
    const response = await api.get<MakerSettings>("/maker/settings");
    return response.data;
  },

  updateSettings: async (data: MakerSettingsUpdate): Promise<MakerSettings> => {
    const response = await api.patch<MakerSettings>("/maker/settings", data);
    return response.data;
  },

  getAvailability: async (
    recipeId: string,
    params?: { batches?: string; location_id?: string },
  ): Promise<AvailabilityResponse> => {
    const response = await api.get<AvailabilityResponse>(
      `/maker/recipes/${recipeId}/availability`,
      { params },
    );
    return response.data;
  },
};
