import type { components } from "@/types/api-generated";
import { api } from "@/lib/api/client";

export type MaintenanceLog = components["schemas"]["MaintenanceLogSchema"];

export type MaintenanceLogCreate =
  components["schemas"]["MaintenanceLogCreate"];

export const equipmentMaintenanceApi = {
  createMaintenanceLog: async (
    data: MaintenanceLogCreate,
  ): Promise<MaintenanceLog> => {
    const response = await api.post<MaintenanceLog>(
      "/equipment/maintenance",
      data,
    );
    return response.data;
  },

  getItemMaintenanceLogs: async (itemId: string): Promise<MaintenanceLog[]> => {
    const response = await api.get<{ items: MaintenanceLog[] }>(
      `/equipment/maintenance/item/${itemId}`,
    );
    return response.data.items;
  },

  deleteMaintenanceLog: async (logId: string): Promise<void> => {
    await api.delete(`/equipment/maintenance/${logId}`);
  },
};
