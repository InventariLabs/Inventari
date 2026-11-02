import { useQuery } from "@tanstack/react-query";
import { breakdownApi } from "@/modules/maker/api/breakdown";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * Read-only cost breakdown for a given template at qty (no state mutation).
 *
 * Pass `recipeId` to resolve the formula an order actually runs; without
 * it the template's default formula answers, which is a different question
 * as soon as a product has a second one.
 */
export function useCostBreakdown(
  templateId: string | undefined,
  qty: string,
  recipeId?: string | null,
) {
  return useQuery({
    queryKey: templateId
      ? queryKeys.maker.breakdown(templateId, qty, recipeId)
      : queryKeys.maker.breakdownNoop,
    queryFn: () =>
      breakdownApi.forTemplate(templateId as string, qty, recipeId),
    enabled: !!templateId && Number(qty) > 0,
  });
}
