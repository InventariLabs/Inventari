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
 * explains it. It stays unasked while the profile hides the value.
 */
export function useStockValueMovement(
  query: StockValueMovementQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.stockAsOf.movement(query),
    queryFn: () => stockValueMovementApi.get(query),
    enabled: enabled && Boolean(query.date_to),
    retry: false,
    staleTime: 60_000,
  });
}
