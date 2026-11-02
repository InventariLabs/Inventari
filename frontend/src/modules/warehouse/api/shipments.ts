/**
 * Shipping a dispatch: the carriers the completion form suggests.
 *
 * The shipment itself travels with the completion (`documentsApi.complete`)
 * and comes back on the document; this is the one read of its own.
 */
import { api } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

export type ShipmentCreate = components["schemas"]["ShipmentCreate"];
export type DocumentShipment = components["schemas"]["DocumentShipmentSchema"];
type CarrierSuggestions = components["schemas"]["CarrierSuggestions"];

export const shipmentsApi = {
  /** The organization's carriers, the most recently used first. */
  carriers: async (): Promise<string[]> => {
    const response = await api.get<CarrierSuggestions>(
      "/warehouse/shipments/carriers",
    );
    return response.data.carriers ?? [];
  },
};
