import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import type { CheckoutApprovalAsk } from "@/modules/equipment/api/equipment_assets";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

export function useMyAssets() {
  return useModuleQuery("equipment", {
    queryKey: [...queryKeys.equipment.all, "my-assets"],
    queryFn: () => equipmentApi.getMyAssets(),
  });
}

export function useMyAssetHistory() {
  return useModuleQuery("equipment", {
    queryKey: [...queryKeys.equipment.all, "my-assets-history"],
    queryFn: () => equipmentApi.getMyAssetHistory(),
  });
}

export function useApprovalStatus(itemId: string) {
  return useQuery({
    queryKey: [...queryKeys.equipment.assets.detail(itemId), "approval"],
    queryFn: () => equipmentApi.getApprovalStatus(itemId),
    enabled: Boolean(itemId),
  });
}

export function useRequestApproval(itemId: string) {
  return useAppMutation(
    (ask?: CheckoutApprovalAsk) => equipmentApi.requestApproval(itemId, ask),
    (qc) => {
      qc.invalidateQueries({
        queryKey: [...queryKeys.equipment.assets.detail(itemId), "approval"],
      });
    },
  );
}
