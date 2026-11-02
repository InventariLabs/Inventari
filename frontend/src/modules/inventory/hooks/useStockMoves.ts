import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { stockMovesApi, type StockMoveFilters } from "@/lib/api/stockMoves";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * One page of the movement ledger.
 *
 * ``keepPreviousData`` because paging a ledger is reading, not loading: the
 * table must not blank out between pages.
 */
export function useStockMoves(filters: StockMoveFilters = {}) {
  return useQuery({
    queryKey: queryKeys.stockMoves.list(filters),
    queryFn: () => stockMovesApi.list(filters),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}
