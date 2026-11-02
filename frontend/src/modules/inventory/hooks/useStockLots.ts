import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  stockLotsApi,
  type LotStatus,
  type StockLotFilters,
} from "@/lib/api/stockLots";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";

/** One page of batches. */
export function useStockLots(filters: StockLotFilters = {}) {
  return useQuery({
    queryKey: queryKeys.stockLots.list(filters),
    queryFn: () => stockLotsApi.list(filters),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/**
 * Hold a batch back, or let it go again.
 *
 * Invalidates the shelves as well as the batches: a recalled batch is
 * flagged on every quant that carries it, and a stale list would go on
 * offering stock the picker may no longer touch.
 */
export function useSetLotStatus() {
  return useAppMutation(
    (vars: { lotId: string; status: LotStatus; reason: string }) =>
      stockLotsApi.setStatus(vars.lotId, vars.status, vars.reason),
    (queryClient, _data, vars) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.stockLots.all,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.stockQuants.all,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.stockLots.detail(vars.lotId),
      });
    },
  );
}
