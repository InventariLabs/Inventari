import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { stockQuantsApi, type StockQuantFilters } from "@/lib/api/stockQuants";
import { queryKeys } from "@/hooks/queries/keys";

/** One page of shelves. */
export function useStockQuants(filters: StockQuantFilters = {}) {
  return useQuery({
    queryKey: queryKeys.stockQuants.list(filters),
    queryFn: () => stockQuantsApi.list(filters),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}
