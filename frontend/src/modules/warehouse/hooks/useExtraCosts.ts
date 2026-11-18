import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  extraCostsApi,
  type CostVarianceInput,
  type ExtraCostInput,
} from "@/modules/warehouse/api/extraCosts";

const key = queryKeys.documents.extraCosts;

/** The costs on this receipt, and what they do to each line. */
export function useExtraCosts(documentId: string, enabled = true) {
  return useQuery({
    queryKey: key(documentId),
    queryFn: () => extraCostsApi.get(documentId),
    enabled: enabled && Boolean(documentId),
    staleTime: 30_000,
  });
}

export function useAddExtraCost(documentId: string) {
  return useAppMutation(
    (input: ExtraCostInput) => extraCostsApi.add(documentId, input),
    (queryClient) => {
      void queryClient.invalidateQueries({ queryKey: key(documentId) });
    },
  );
}

export function useRemoveExtraCost(documentId: string) {
  return useAppMutation(
    (costId: string) => extraCostsApi.remove(documentId, costId),
    (queryClient) => {
      void queryClient.invalidateQueries({ queryKey: key(documentId) });
    },
  );
}

const variancesKey = queryKeys.documents.costVariances;

/** A page of the costs that reached no product, with the sums of them all. */
export function useCostVariances(page: { limit: number; offset: number }) {
  return useQuery({
    queryKey: [...variancesKey, page],
    queryFn: () => extraCostsApi.listVariances(page),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useAddCostVariance(documentId: string) {
  return useAppMutation(
    (input: CostVarianceInput) => extraCostsApi.addVariance(documentId, input),
    (queryClient) => {
      void queryClient.invalidateQueries({ queryKey: key(documentId) });
      void queryClient.invalidateQueries({ queryKey: variancesKey });
    },
  );
}

export function useRemoveCostVariance(documentId: string) {
  return useAppMutation(
    (varianceId: string) =>
      extraCostsApi.removeVariance(documentId, varianceId),
    (queryClient) => {
      void queryClient.invalidateQueries({ queryKey: key(documentId) });
      void queryClient.invalidateQueries({ queryKey: variancesKey });
    },
  );
}
