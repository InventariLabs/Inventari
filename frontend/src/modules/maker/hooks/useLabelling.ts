import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { labellingApi } from "@/modules/maker/api/labelling";
import type { LabelFactsUpdate } from "@/modules/maker/types/maker";

export function useLabelFacts(templateId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.maker.labelFacts(templateId ?? ""),
    queryFn: () => labellingApi.facts(templateId as string),
    enabled: !!templateId,
  });
}

/** Save a product's label facts. Every recipe that uses the product, and
 *  every made product above it, reads them, so every label is read again. */
export function useSetLabelFacts(templateId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (facts: LabelFactsUpdate) =>
      labellingApi.setFacts(templateId, facts),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.maker.labelFacts(templateId), saved);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.maker.labelAll,
      });
    },
  });
}

export function useRecipeLabel(recipeId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maker.recipeLabel(recipeId ?? ""),
    queryFn: () => labellingApi.recipeLabel(recipeId as string),
    enabled: !!recipeId,
  });
}
