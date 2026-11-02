import { api, getEveryPage } from "@/lib/api/client";
import type {
  ApiKey,
  ApiKeyCapabilities,
  ApiKeyCreate,
  ApiKeyCreated,
} from "./types";

export const apiKeysApi = {
  getAll: async (): Promise<ApiKey[]> => {
    return getEveryPage<ApiKey>("/api-keys");
  },

  getCapabilities: async (): Promise<ApiKeyCapabilities> => {
    const response = await api.get<ApiKeyCapabilities>(
      "/api-keys/capabilities",
    );
    return response.data;
  },

  create: async (data: ApiKeyCreate): Promise<ApiKeyCreated> => {
    const response = await api.post<ApiKeyCreated>("/api-keys", data);
    return response.data;
  },

  revoke: async (id: string): Promise<void> => {
    await api.delete(`/api-keys/${id}`);
  },
};
