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
 * A dispatch that leaves the company goes with a carrier; an internal issue
 * (INTERNAL_OUT, and RW as the legacy name for it) stays inside, so no screen
 * asks it for one.
 */
export const leavesWithCarrier = (type: string) =>
  type === "OUT" || type === "WZ";

/**
 * Every dispatch of a picking sheet is internal: none of it asks for a
 * carrier. Types that could not be found ask, as before.
 */
export const allWithoutCarrier = (types: string[]) =>
  types.length > 0 && types.every((type) => !leavesWithCarrier(type));

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
