import { equipmentApi } from "@/modules/equipment/api/equipment";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

export function useAssetValuation(itemId: string) {
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.valuation.asset(itemId),
    queryFn: () => equipmentApi.getAssetValuation(itemId),
    extraEnabled: Boolean(itemId),
  });
}

export function useFleetValuation(enabled = true) {
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.valuation.fleet,
    queryFn: () => equipmentApi.getFleetValuation(),
    extraEnabled: enabled,
  });
}
