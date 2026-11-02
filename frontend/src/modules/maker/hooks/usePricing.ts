import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pricingApi } from "@/modules/maker/api/pricing";
import { queryKeys } from "@/hooks/queries/keys";
import type { PricingRequest } from "@/modules/maker/api/pricing";

export function usePricingCompute() {
  return useMutation({
    mutationFn: (req: PricingRequest) => pricingApi.compute(req),
  });
}

export function useMargin(templateId: string | undefined) {
  return useQuery({
    queryKey: templateId
      ? queryKeys.maker.margin(templateId)
      : queryKeys.maker.marginNoop,
    queryFn: () => pricingApi.getMargin(templateId as string),
    enabled: !!templateId,
  });
}

export function useSetMargin(templateId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (targetMarginPct: string) =>
      pricingApi.setMargin(templateId, targetMarginPct),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.maker.margin(templateId),
      });
    },
  });
}
