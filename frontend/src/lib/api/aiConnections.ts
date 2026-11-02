import { api, getEveryPage } from "./client";
import type {
  AiBindingRequest,
  AiConnection,
  AiConnectionDraft,
  AiConnectionTestResult,
  AiConnectionUpdate,
  AiPurpose,
} from "@/types/ai";

export const aiConnectionsApi = {
  list: async (): Promise<AiConnection[]> => {
    return getEveryPage<AiConnection>("/ai-connections");
  },

  create: async (data: AiConnectionDraft): Promise<AiConnection> => {
    const response = await api.post<AiConnection>("/ai-connections", data);
    return response.data;
  },

  update: async (
    connectionId: string,
    data: AiConnectionUpdate,
  ): Promise<AiConnection> => {
    const response = await api.put<AiConnection>(
      `/ai-connections/${connectionId}`,
      data,
    );
    return response.data;
  },

  delete: async (connectionId: string): Promise<void> => {
    await api.delete(`/ai-connections/${connectionId}`);
  },

  listPurposes: async (): Promise<AiPurpose[]> => {
    return getEveryPage<AiPurpose>("/ai-connections/purposes");
  },

  setBinding: async (data: AiBindingRequest): Promise<void> => {
    await api.put("/ai-connections/bindings", data);
  },

  test: async (
    data: Pick<
      AiConnectionDraft,
      "provider" | "api_key" | "api_base_url" | "model_name" | "capabilities"
    >,
  ): Promise<AiConnectionTestResult> => {
    // `capabilities` decides which contract probe the backend runs, so the
    // draft's own declaration travels with the request. The payload is
    // built field by field on purpose: the test endpoint forbids extra
    // fields (extra='forbid'), and the caller's draft carries save-time
    // baggage — the name, the tuning knobs — that would turn the test
    // into a 422 about "name: Extra inputs are not permitted" before the
    // URL guard ever spoke.
    const response = await api.post<AiConnectionTestResult>(
      "/ai-connections/test",
      {
        provider: data.provider,
        api_key: data.api_key,
        api_base_url: data.api_base_url,
        model_name: data.model_name,
        capabilities: data.capabilities,
      },
    );
    return response.data;
  },
};
