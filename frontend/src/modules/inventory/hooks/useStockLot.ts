import { useQuery } from "@tanstack/react-query";
import { stockLotsApi } from "@/lib/api/stockLots";
import { queryKeys } from "@/hooks/queries/keys";

/** One batch: what it is, and what is left of it. */
export function useStockLot(lotId: string) {
  return useQuery({
    queryKey: queryKeys.stockLots.detail(lotId),
    queryFn: () => stockLotsApi.get(lotId),
    enabled: Boolean(lotId),
  });
}

/** The batch's suppliers and customers, and those of what was made of it. */
export function useLotTrace(lotId: string) {
  return useQuery({
    queryKey: queryKeys.stockLots.trace(lotId),
    queryFn: () => stockLotsApi.trace(lotId),
    enabled: Boolean(lotId),
  });
}
