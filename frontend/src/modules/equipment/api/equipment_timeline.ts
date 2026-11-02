import type { components } from "@/types/api-generated";
import { api } from "@/lib/api/client";

/** One server-assembled timeline entry (see GET /equipment/assets/{id}/timeline).

 * Which fields carry content depends on `kind`: a handover names the holder
 * (and on the way back, who actually checked the return in), a maintenance
 * entry brings the service record's own columns, a status change names the
 * two states. Optional per kind — one shape carries the union. */
export type AssetTimelineEvent = components["schemas"]["AssetTimelineEvent"];

export const assetTimelineApi = {
  getAssetTimeline: async (itemId: string): Promise<AssetTimelineEvent[]> => {
    const response = await api.get<{ events: AssetTimelineEvent[] }>(
      `/equipment/assets/${itemId}/timeline`,
    );
    return response.data.events;
  },
};
