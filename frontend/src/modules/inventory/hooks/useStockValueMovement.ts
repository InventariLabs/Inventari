import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import {
  stockValueMovementApi,
  type StockValueMovementQuery,
} from "../api/stockValueMovement";

/**
 * The value of the stock over a period.
 *
 * No retry, for the reason the stock on a date has none: the interesting
 * failure is a refusal, and repeating it only delays the sentence that
 * explains it.
 */
export function useStockValueMovement(query: StockValueMovementQuery) {
  return useQuery({
    queryKey: queryKeys.stockAsOf.movement(query),
    queryFn: () => stockValueMovementApi.get(query),
    enabled: Boolean(query.date_from && query.date_to),
    retry: false,
    staleTime: 60_000,
  });
}
