import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  extraCostsApi,
  type ExtraCostInput,
} from "@/modules/warehouse/api/extraCosts";

const key = (documentId: string) => ["document-extra-costs", documentId];

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
