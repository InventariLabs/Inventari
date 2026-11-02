/**
 * This installation's name, version, licence and source link —
 * GET /api/v1/about, read by the About screen.
 */
import { api } from "./client";
import type { components } from "@/types/api-generated";

export type AboutInfo = components["schemas"]["AboutResponse"];

export const aboutApi = {
  get: async (): Promise<AboutInfo> => {
    const response = await api.get<AboutInfo>("/about");
    return response.data;
  },
};
