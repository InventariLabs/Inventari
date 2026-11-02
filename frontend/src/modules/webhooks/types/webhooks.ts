import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";
// Webhook types.

export type WebhookEndpoint = components["schemas"]["WebhookEndpointResponse"];

export type WebhookEndpointCreate =
  components["schemas"]["WebhookEndpointCreate"];

/** What a caller sends: the delivery policy it leaves out is the server's default. */
export type WebhookEndpointCreateInput = WithServerDefaults<
  WebhookEndpointCreate,
  "http_method" | "max_retries" | "retry_backoff_seconds" | "timeout_seconds"
>;

export type WebhookEndpointUpdate =
  components["schemas"]["WebhookEndpointUpdate"];

export type WebhookDelivery = components["schemas"]["WebhookDeliveryResponse"];

export interface WebhookDeliveryList {
  items: WebhookDelivery[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface WebhookAvailableEvent {
  event_type: string;
  /** English sentence from the API — the fallback when a locale lacks the key. */
  description: string;
  /** Module that emits this event; null for a core event. */
  source_module: string | null;
  /** Whether that module is enabled here. */
  available: boolean;
}

export type WebhookTestResult = components["schemas"]["TestWebhookResponse"];
