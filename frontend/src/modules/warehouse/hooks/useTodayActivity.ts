import { documentsApi } from "@/modules/warehouse/api/documents";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

/** How many of the day's entries the feed reads at once. */
const FEED_LIMIT = 50;

/**
 * The reader's own day as two instants: local midnight and the midnight
 * after it. A posting is "today" by the clock of the person reading the feed,
 * not by the server's timezone, so the boundary is computed here — the same
 * reason the To do queue asks for the reader's `date_to`.
 */
export function todayBounds(now: Date = new Date()): {
  from: string;
  to: string;
} {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return { from: start.toISOString(), to: end.toISOString() };
}

/**
 * What happened in the warehouse today: documents posted since the reader's
 * midnight, newest posting first, each carrying who posted it. `warehouseId`
 * narrows the feed to one place and the shelves under it; `null` is the
 * whole organization.
 */
export function useTodayActivity(warehouseId: string | null = null) {
  return useModuleQuery("warehouse", {
    queryKey: [...queryKeys.documents.all, "today", warehouseId],
    queryFn: () => {
      const { from, to } = todayBounds();
      return documentsApi.list({
        status: "COMPLETED",
        completed_from: from,
        completed_to: to,
        location_id: warehouseId ?? undefined,
        sort_by: "completed_at",
        sort_order: "desc",
        limit: FEED_LIMIT,
      });
    },
    // A warehouse keeps working while the screen stands open.
    refetchInterval: 60_000,
  });
}
