import { itemsApi } from "@/lib/api/items";
import { attentionCount } from "@/modules/shared/hooks/useAttentionCounts";
import { queryKeys } from "@/hooks/queries/keys";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import { useLauncherStatusBadge } from "@/modules/shared/hooks/useLauncherStatusBadge";

/**
 * useInventoryStatusBadge — returns a status badge for the launcher tile.
 * Shows what the overview's heading shows, narrowed by the organization's
 * "show module data" setting as that heading is: a tile that said "3 low
 * stock" opened a card saying 14 and a list of 17. Returns null while loading
 * or when count is zero; on error a `failed` badge.
 */
export function useInventoryStatusBadge() {
  const excludeModuleContexts = !useShowModuleData();
  return useLauncherStatusBadge({
    queryKey: [...queryKeys.stats.launcherBadge, excludeModuleContexts],
    queryFn: () =>
      itemsApi.getAttentionCounts({
        exclude_module_contexts: excludeModuleContexts,
      }),
    labelKey: "statusBadge.needsAttention",
    labelNs: "inventory",
    staleTime: 2 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    extractCount: attentionCount,
  });
}
