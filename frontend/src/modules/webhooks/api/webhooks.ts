import { api, getEveryPage } from "@/lib/api/client";
import type {
  WebhookEndpoint,
  WebhookEndpointCreateInput,
  WebhookEndpointUpdate,
  WebhookDeliveryList,
  WebhookAvailableEvent,
  WebhookTestResult,
} from "@/modules/webhooks/types/webhooks";

export const webhooksApi = {
  getAvailableEvents: async (): Promise<WebhookAvailableEvent[]> => {
    const response = await api.get<WebhookAvailableEvent[]>("/webhooks/events");
    return response.data;
  },

  getAll: async (): Promise<WebhookEndpoint[]> => {
    return getEveryPage<WebhookEndpoint>("/webhooks/endpoints");
  },

  getById: async (id: string): Promise<WebhookEndpoint> => {
    const response = await api.get<WebhookEndpoint>(
      `/webhooks/endpoints/${id}`,
    );
    return response.data;
  },

  create: async (
    data: WebhookEndpointCreateInput,
  ): Promise<WebhookEndpoint> => {
    const response = await api.post<WebhookEndpoint>(
      "/webhooks/endpoints",
      data,
    );
    return response.data;
  },

  update: async (
    id: string,
    data: WebhookEndpointUpdate,
  ): Promise<WebhookEndpoint> => {
    const response = await api.put<WebhookEndpoint>(
      `/webhooks/endpoints/${id}`,
      data,
    );
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/webhooks/endpoints/${id}`);
  },

  test: async (id: string): Promise<WebhookTestResult> => {
    const response = await api.post<WebhookTestResult>(
      `/webhooks/endpoints/${id}/test`,
    );
    return response.data;
  },

  reactivate: async (id: string): Promise<WebhookEndpoint> => {
    const response = await api.post<WebhookEndpoint>(
      `/webhooks/endpoints/${id}/reactivate`,
    );
    return response.data;
  },

  getDeliveries: async (
    id: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<WebhookDeliveryList> => {
    const params: Record<string, string | number> = { limit };
    if (cursor) params.cursor = cursor;
    const response = await api.get<WebhookDeliveryList>(
      `/webhooks/endpoints/${id}/deliveries`,
      { params },
    );
    return response.data;
  },
};
