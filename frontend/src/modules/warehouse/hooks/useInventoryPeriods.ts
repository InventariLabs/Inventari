import { useAppMutation } from "@/lib/api/mutationFactory";
import { inventoryPeriodsApi } from "@/modules/warehouse/api/documents";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { invalidation } from "@/lib/api/invalidation";

export function useInventoryPeriods(year?: number) {
  return useModuleQuery("warehouse", {
    queryKey: [...queryKeys.documents.periods, year],
    queryFn: () => inventoryPeriodsApi.list(year),
  });
}

export function useClosePeriod() {
  return useAppMutation(
    ({ year, month, notes }: { year: number; month: number; notes?: string }) =>
      inventoryPeriodsApi.close(year, month, notes),
    (qc) => {
      invalidation.inventoryPeriods(qc);
    },
  );
}

export function useReopenPeriod() {
  return useAppMutation(
    ({ year, month, notes }: { year: number; month: number; notes?: string }) =>
      inventoryPeriodsApi.reopen(year, month, notes),
    (qc) => {
      invalidation.inventoryPeriods(qc);
    },
  );
}
