import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";
import { assertFileSize } from "@/utils/fileValidation";

export type WarrantyAlert = components["schemas"]["WarrantyAlert"];

type EquipmentDashboard = components["schemas"]["EquipmentDashboard"];

export type ImportAnalyzeResult = components["schemas"]["ImportAnalyzeResult"];

export type ImportExecuteResult = components["schemas"]["ImportExecuteResult"];

export const equipmentDashboardApi = {
  getDashboard: async (): Promise<EquipmentDashboard> => {
    const response = await api.get<EquipmentDashboard>("/equipment/dashboard");
    return response.data;
  },

  /** With no days given, the server looks as far ahead as the settings say. */
  getWarrantyAlerts: async (days?: number): Promise<WarrantyAlert[]> => {
    return getEveryPage<WarrantyAlert>("/equipment/warranty-alerts", { days });
  },

  analyzeImport: async (file: File): Promise<ImportAnalyzeResult> => {
    assertFileSize(file);
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<ImportAnalyzeResult>(
      "/equipment/import/analyze",
      formData,
    );
    return response.data;
  },

  executeImport: async (
    file: File,
    mapping: Record<string, string>,
    defaultLocationId?: string,
    defaultCategoryId?: string,
  ): Promise<ImportExecuteResult> => {
    assertFileSize(file);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mapping_json", JSON.stringify(mapping));
    if (defaultLocationId)
      formData.append("default_location_id", defaultLocationId);
    if (defaultCategoryId)
      formData.append("default_category_id", defaultCategoryId);
    const response = await api.post<ImportExecuteResult>(
      "/equipment/import/execute",
      formData,
    );
    return response.data;
  },
};
