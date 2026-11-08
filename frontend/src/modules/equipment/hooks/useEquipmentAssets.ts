import { useQuery } from "@tanstack/react-query";
import { itemsApi } from "@/lib/api/items";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";
import {
  equipmentAssetsApi,
  type EquipmentAssetItem,
  type EquipmentAssetListParams,
  type EquipmentAssetListResponse,
} from "@/modules/equipment/api/equipment_assets";

export function useEquipmentAssets(params: EquipmentAssetListParams = {}) {
  return useModuleQuery<EquipmentAssetListResponse>("equipment", {
    queryKey: queryKeys.equipment.assets.list(params),
    queryFn: () =>
      equipmentAssetsApi.listAssets({
        search: params.search || undefined,
        category_id: params.category_id || undefined,
        location_id: params.location_id || undefined,
        status: params.status || undefined,
        checked_out: params.checked_out || undefined,
        hide_retired: params.hide_retired || undefined,
        sort: params.sort,
        sort_dir: params.sort_dir,
        offset: params.offset ?? 0,
        limit: params.limit ?? 50,
      }),
  });
}

export function useEquipmentAsset(itemId: string) {
  return useQuery<EquipmentAssetItem>({
    queryKey: queryKeys.equipment.assets.detail(itemId),
    // The card keeps rendering after the archive — Restore and Purge live
    // under it — so the read names the archive. The default read answers
    // the archive-pointing 404, which left this page with nothing to show.
    queryFn: () =>
      itemsApi.getById(itemId, {
        includeArchived: true,
      }) as Promise<EquipmentAssetItem>,
    enabled: Boolean(itemId),
  });
}
