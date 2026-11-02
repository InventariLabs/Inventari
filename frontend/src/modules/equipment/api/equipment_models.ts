import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";

export type EquipmentModel = components["schemas"]["EquipmentModelSchema"];

export type EquipmentModelCreate =
  components["schemas"]["EquipmentModelCreate"];

export type EquipmentModelUpdate =
  components["schemas"]["EquipmentModelUpdate"];

export const equipmentModelsApi = {
  listModels: async (): Promise<EquipmentModel[]> => {
    return getEveryPage<EquipmentModel>("/equipment/models");
  },

  createModel: async (data: EquipmentModelCreate): Promise<EquipmentModel> => {
    const response = await api.post<EquipmentModel>("/equipment/models", data);
    return response.data;
  },

  updateModel: async (
    modelId: string,
    data: EquipmentModelUpdate,
  ): Promise<EquipmentModel> => {
    const response = await api.put<EquipmentModel>(
      `/equipment/models/${modelId}`,
      data,
    );
    return response.data;
  },

  deleteModel: async (modelId: string): Promise<void> => {
    await api.delete(`/equipment/models/${modelId}`);
  },

  cloneModel: async (modelId: string): Promise<EquipmentModel> => {
    const response = await api.post<EquipmentModel>(
      `/equipment/models/${modelId}/clone`,
    );
    return response.data;
  },
};
