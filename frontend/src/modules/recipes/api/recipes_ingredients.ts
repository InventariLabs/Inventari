import { api, getEveryPage } from "@/lib/api/client";
import { assertFileSize } from "@/utils/fileValidation";
import type {
  IngredientDefault,
  IngredientDefaultListResponse,
  IngredientDefaultLookupResponse,
  IngredientDefaultCreate,
  ImportDefaultsResult,
  UnitConversion,
  UnitConversionCreate,
  UnitConversionUpdate,
} from "@/modules/recipes/types/nutrition-defaults";

export const recipesIngredientsApi = {
  listIngredientDefaults: async (params?: {
    lang?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }): Promise<IngredientDefaultListResponse> => {
    const response = await api.get<IngredientDefaultListResponse>(
      "/recipes/ingredient-defaults",
      { params },
    );
    return response.data;
  },

  lookupIngredientDefault: async (
    name: string,
    lang = "en",
  ): Promise<IngredientDefaultLookupResponse> => {
    const response = await api.get<IngredientDefaultLookupResponse>(
      "/recipes/ingredient-defaults/lookup",
      { params: { name, lang } },
    );
    return response.data;
  },

  createIngredientDefault: async (
    data: IngredientDefaultCreate,
  ): Promise<IngredientDefault> => {
    const response = await api.post<IngredientDefault>(
      "/recipes/ingredient-defaults",
      data,
    );
    return response.data;
  },

  deleteIngredientDefault: async (id: string): Promise<void> => {
    await api.delete(`/recipes/ingredient-defaults/${id}`);
  },

  importIngredientDefaults: async (
    file: File,
    lang = "en",
  ): Promise<ImportDefaultsResult> => {
    assertFileSize(file);
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<ImportDefaultsResult>(
      "/recipes/ingredient-defaults/import",
      formData,
      { params: { lang } },
    );
    return response.data;
  },

  exportIngredientDefaults: async (
    lang = "en",
    fmt: "json" | "csv" = "csv",
  ): Promise<Blob> => {
    const response = await api.get("/recipes/ingredient-defaults/export", {
      params: { lang, fmt },
      responseType: "blob",
    });
    return response.data;
  },

  listUnitConversions: async (params?: {
    lang?: string;
  }): Promise<UnitConversion[]> => {
    return getEveryPage<UnitConversion>("/recipes/unit-conversions", params);
  },

  createUnitConversion: async (
    data: UnitConversionCreate,
  ): Promise<UnitConversion> => {
    const response = await api.post<UnitConversion>(
      "/recipes/unit-conversions",
      data,
    );
    return response.data;
  },

  updateUnitConversion: async (
    id: string,
    data: UnitConversionUpdate,
  ): Promise<UnitConversion> => {
    const response = await api.put<UnitConversion>(
      `/recipes/unit-conversions/${id}`,
      data,
    );
    return response.data;
  },

  deleteUnitConversion: async (id: string): Promise<void> => {
    await api.delete(`/recipes/unit-conversions/${id}`);
  },
};
