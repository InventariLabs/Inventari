import { equipmentApi } from "@/modules/equipment/api/equipment";
import { queryKeys } from "@/hooks/queries/keys";
import { useLauncherStatusBadge } from "@/modules/shared/hooks/useLauncherStatusBadge";

/**
 * useEquipmentStatusBadge — returns a status badge for the launcher tile.
 * Shows the warranty alerts of the overview it opens, as far ahead as the
 * module's settings say: a tile that always asked for 30 days said 2 over a
 * screen saying 4. Returns null while loading or when count is zero; on error a `failed` badge.
 */
export function useEquipmentStatusBadge() {
  return useLauncherStatusBadge({
    queryKey: queryKeys.equipment.warrantyBadge,
    queryFn: () => equipmentApi.getWarrantyAlerts(),
    labelKey: "equipment:statusBadge.warrantyAlerts",
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
    extractCount: (data) => data.length,
  });
}
