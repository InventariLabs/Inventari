import { useQuery, useQueryClient } from "@tanstack/react-query";
import { planningApi } from "@/modules/maker/api/planning";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import { useAppMutation } from "@/lib/api/mutationFactory";
import type {
  NeedsScope,
  OrderMissingResult,
  PlanIntermediatesResult,
} from "@/modules/maker/types/maker";

/** The combined needs of the runs a scope names; idle until it names some. */
export function useNeeds(scope: NeedsScope | null) {
  return useQuery({
    queryKey: queryKeys.maker.needs(scope),
    queryFn: () => planningApi.needs(scope as NeedsScope),
    enabled: scope !== null,
    placeholderData: (prev) => prev,
  });
}

/** Order what is missing; purchase orders and shopping lists change with it. */
export function useOrderMissing(errorFallback?: string) {
  const queryClient = useQueryClient();
  return useAppMutation<OrderMissingResult, NeedsScope>(
    (scope) => planningApi.orderMissing(scope),
    () => {
      invalidation.maker(queryClient);
      invalidation.purchaseOrders(queryClient);
      invalidation.shoppingLists(queryClient);
    },
    { errorFallback },
  );
}

/** Plan a run of each missing intermediate product. */
export function usePlanIntermediates(errorFallback?: string) {
  const queryClient = useQueryClient();
  return useAppMutation<PlanIntermediatesResult, NeedsScope>(
    (scope) => planningApi.planIntermediates(scope),
    () => {
      invalidation.maker(queryClient);
    },
    { errorFallback },
  );
}
