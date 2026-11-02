import { keepPreviousData } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { webhooksApi } from "@/modules/webhooks/api/webhooks";
import { invalidation } from "@/lib/api/invalidation";
import type {
  WebhookEndpoint,
  WebhookEndpointCreateInput,
  WebhookEndpointUpdate,
  WebhookDeliveryList,
  WebhookAvailableEvent,
} from "@/modules/webhooks/types/webhooks";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

export function useWebhooks() {
  return useModuleQuery<WebhookEndpoint[]>("webhooks", {
    queryKey: queryKeys.webhooks.all,
    queryFn: () => webhooksApi.getAll(),
  });
}

export function useWebhookAvailableEvents() {
  return useModuleQuery<WebhookAvailableEvent[]>("webhooks", {
    queryKey: queryKeys.webhooks.events,
    queryFn: () => webhooksApi.getAvailableEvents(),
    staleTime: Infinity,
  });
}

export function useWebhookDeliveries(
  webhookId: string,
  cursor: string | null = null,
  pageSize = 20,
) {
  return useModuleQuery<WebhookDeliveryList>("webhooks", {
    queryKey: queryKeys.webhooks.deliveries(webhookId, cursor),
    queryFn: () => webhooksApi.getDeliveries(webhookId, cursor, pageSize),
    placeholderData: keepPreviousData,
  });
}

export function useCreateWebhook() {
  return useAppMutation<WebhookEndpoint, WebhookEndpointCreateInput>(
    webhooksApi.create,
    (qc) => {
      invalidation.webhooks(qc);
    },
  );
}

export function useUpdateWebhook() {
  return useAppMutation<
    WebhookEndpoint,
    { id: string; data: WebhookEndpointUpdate }
  >(
    ({ id, data }) => webhooksApi.update(id, data),
    (qc) => {
      invalidation.webhooks(qc);
    },
  );
}

export function useDeleteWebhook() {
  return useAppMutation<void, string>(webhooksApi.delete, (qc) => {
    invalidation.webhooks(qc);
  });
}

export function useTestWebhook() {
  // A test is a delivery: it moves `last_status_code` and
  // `consecutive_failures` on the endpoint, and the card kept showing "never"
  // and a green dot while the backend already had four failures on record.
  return useAppMutation(webhooksApi.test, (qc) => {
    invalidation.webhooks(qc);
  });
}

export function useReactivateWebhook() {
  return useAppMutation<WebhookEndpoint, string>(
    webhooksApi.reactivate,
    (qc) => {
      invalidation.webhooks(qc);
    },
  );
}
