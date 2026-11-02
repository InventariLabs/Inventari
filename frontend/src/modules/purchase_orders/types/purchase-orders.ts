import type { components } from "@/types/api-generated";
// Purchase Order types.

export type POStatus =
  "DRAFT" | "PENDING_APPROVAL" | "CONFIRMED" | "CANCELLED" | "COMPLETED";

export interface PurchaseOrderListParams {
  search?: string;
  status?: POStatus;
  /** One supplier's orders — the link the partner card follows. */
  partner_id?: string;
  limit?: number;
  offset?: number;
}

export type POLine = components["schemas"]["PurchaseOrderLineSchema"];

export type PurchaseOrder = components["schemas"]["PurchaseOrderSchema"];

export type PurchaseOrderListResponse =
  components["schemas"]["PurchaseOrderListResponse"];

/**
 * An order as the list shows it: its lines counted (`line_count`) and summed
 * per unit (`unit_progress`). The list carries the lines themselves only when
 * asked `with_lines`; a screen that needs them reads the order.
 */
export type PurchaseOrderRow = Omit<
  components["schemas"]["PurchaseOrderListRowSchema"],
  "lines"
>;

export type PurchaseOrderCreate = components["schemas"]["PurchaseOrderCreate"];

export type PurchaseOrderUpdate = components["schemas"]["PurchaseOrderUpdate"];

export type POSettings = components["schemas"]["POSettingsSchema"];

export type POSettingsUpdate = components["schemas"]["POSettingsUpdate"];
