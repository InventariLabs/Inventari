import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { packingApi, type PackingView } from "@/modules/warehouse/api/packing";

/** The dispatch's packages, and what of each line is left to pack. */
export function usePacking(documentId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.documents.packing(documentId),
    queryFn: () => packingApi.get(documentId),
    enabled: enabled && Boolean(documentId),
  });
}

/**
 * One door for every packing write.
 *
 * Each write answers with the whole view, so the answer replaces the cached
 * one instead of asking again; the variable is the write itself, which lets
 * "open a package, then scan into it" travel as one mutation.
 */
export function usePackingWrite(documentId: string) {
  const { t } = useTranslation("warehouse");
  return useAppMutation(
    (write: () => Promise<PackingView>) => write(),
    (queryClient, view) => {
      queryClient.setQueryData(queryKeys.documents.packing(documentId), view);
    },
    { errorFallback: t("packing.errors.writeFailed") },
  );
}
