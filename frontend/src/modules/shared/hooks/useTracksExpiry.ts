import { api } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { useStorageTypesTrackExpiry } from "./useStorages";

/**
 * Whether this organization tracks expiry — the one decision, for the health
 * card, the detail cards, the alerts and the products list alike.
 *
 * Two signals, either of which settles it: a location that behaves that way, or
 * a record that carries a date. Four screens used to ask their own version of
 * this question, and two of them disagreed in the same organization.
 *
 * The second signal is the statistics overview, read over its route under the
 * key the stats module's own overview uses, so both share one answer. With the
 * stats module off it is never asked, and the locations decide alone. It lives
 * here rather than in stats because the products list asks it too, and stats
 * is optional to the inventory.
 */
export function useTracksExpiry(): boolean {
  const byStorageType = useStorageTypesTrackExpiry();
  const { data: overview } = useModuleQuery("stats", {
    queryKey: queryKeys.stats.overview,
    queryFn: async () =>
      (await api.get<{ tracks_expiry?: boolean }>("/stats/overview")).data,
  });
  return byStorageType || Boolean(overview?.tracks_expiry);
}
