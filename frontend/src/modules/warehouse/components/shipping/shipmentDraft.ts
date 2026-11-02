import type { TFunction } from "i18next";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";

/** What the shipping fields hold while the dispatch is being completed. */
export interface ShipmentDraft {
  carrier: string;
  trackingNumber: string;
}

export const EMPTY_SHIPMENT: ShipmentDraft = {
  carrier: "",
  trackingNumber: "",
};

/**
 * The shipment a completion carries — none when no carrier was named, so a
 * dispatch completed with both fields empty sends what it always sent.
 */
export function shipmentPayload(
  draft: ShipmentDraft,
): ShipmentCreate | undefined {
  const carrier = draft.carrier.trim();
  if (!carrier) return undefined;
  const trackingNumber = draft.trackingNumber.trim();
  return trackingNumber
    ? { carrier, tracking_number: trackingNumber }
    : { carrier };
}

/**
 * A tracking number with no carrier is the one draft that cannot travel: the
 * number means nothing without the company it belongs to, and dropping it
 * silently would lose what the worker just typed.
 */
export function shipmentError(
  draft: ShipmentDraft,
  t: TFunction,
): string | undefined {
  return draft.trackingNumber.trim() && !draft.carrier.trim()
    ? t("warehouse:shipping.carrierNeeded")
    : undefined;
}
