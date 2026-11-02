import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { shipmentsApi } from "@/modules/warehouse/api/shipments";

/** The carriers this organization has shipped with, for the carrier field. */
export function useCarrierSuggestions(enabled = true) {
  return useQuery({
    queryKey: queryKeys.documents.carriers,
    queryFn: shipmentsApi.carriers,
    enabled,
  });
}
