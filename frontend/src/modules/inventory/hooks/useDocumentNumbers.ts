import { useQuery } from "@tanstack/react-query";

import { api } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * The numbers of one page's document sources, one ask for the page.
 *
 * A trail of movements carries its document sources as bare ids; naming a
 * source with its number asks the register for exactly the rows shown, not
 * a detail fetch per row. Disabled when the caller has no document rows on
 * the page — a page of adjustments costs nothing — and when `enabled` says
 * the register is not there to ask (the module switched off).
 *
 * The register is the warehouse module's, read over its HTTP route with this
 * module's own client: the warehouse is optional here, and an import of its
 * files cannot be.
 */
export function useDocumentNumbers(
  ids: (string | null | undefined)[],
  enabled = true,
) {
  const named = [...new Set(ids.filter((id): id is string => !!id))].sort();

  return useQuery({
    queryKey: queryKeys.documents.sourceNumbers(named),
    queryFn: async () => {
      const { data: page } = await api.get<{
        items: { id: string; number: string }[];
      }>("/warehouse/documents", {
        params: { ids: named, limit: 100 },
        // `ids` repeats (?ids=a&ids=b); axios would otherwise send ids[]=a,
        // a name the server does not read, and the list came back unfiltered.
        paramsSerializer: { indexes: null },
      });
      const numbers: Record<string, string> = {};
      for (const doc of page.items) numbers[doc.id] = doc.number;
      return numbers;
    },
    enabled: enabled && named.length > 0,
    staleTime: 5 * 60 * 1000,
  });
}
