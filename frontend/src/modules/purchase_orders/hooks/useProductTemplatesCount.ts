import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/hooks/queries/keys";
import { productTemplatesApi } from "@/lib/api/productTemplates";

/**
 * Whether the product catalog is empty.
 *
 * The search endpoint needs a 2-char query, so an empty catalog used to be
 * discoverable only inside an open form. The count gates the pricelist and
 * reorder-rule CTAs before they open.
 */
export function useProductTemplatesCount() {
  return useQuery({
    queryKey: queryKeys.productTemplates.count,
    queryFn: productTemplatesApi.count,
    staleTime: 30_000,
  });
}
