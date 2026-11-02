import { useQuery } from "@tanstack/react-query";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * How much of a product the organization holds on its shelves.
 *
 * The low-stock threshold is one value per product, so the screen that
 * sets one has to show the quantity it will be measured against. It used
 * to show the quantity of whichever record the reader had opened, and
 * offered to copy that number into the field: on a product kept in six
 * places, "set the alert to what is here now" set it to a sixth of what
 * was there, and the alert then never fired.
 *
 * The sum is the backend's — the same one the dashboard tile and the
 * purchasing engine read — and is not recomputed here from the rows a
 * list happens to be showing.
 */
export function useProductTemplateStock(templateId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.productTemplates.stock(templateId ?? ""),
    queryFn: () => productTemplatesApi.getStock(templateId as string),
    enabled: !!templateId,
  });
}
