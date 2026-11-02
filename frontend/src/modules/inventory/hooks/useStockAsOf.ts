import { useQuery } from "@tanstack/react-query";
import { stockAsOfApi, type StockAsOfQuery } from "@/lib/api/stockAsOf";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * The stock on a date.
 *
 * No retry: the interesting failure here is a refusal — a date the ledger
 * cannot answer for — and repeating it three times only delays the sentence
 * that explains why.
 */
export function useStockAsOf(query: StockAsOfQuery, enabled = true) {
  return useQuery({
    queryKey: queryKeys.stockAsOf.report(query),
    queryFn: () => stockAsOfApi.get(query),
    enabled: enabled && Boolean(query.as_of),
    retry: false,
    staleTime: 60_000,
  });
}
