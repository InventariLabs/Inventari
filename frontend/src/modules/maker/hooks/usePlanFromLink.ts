import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { queryKeys } from "@/hooks/queries/keys";
import { makerProductsApi } from "@/modules/maker/api/products";
import type { PreselectedProduct } from "@/modules/maker/hooks/useProductionSheet";

/**
 * A reorder task for a product that is made here lands on the production list
 * with the product and the missing quantity named in the link
 * (`?plan=<product>&quantity=<n>`). Once the product is read, the form can open
 * as a plan for it; `clearPlan` drops the link when the form closes.
 */
export function usePlanFromLink(): {
  planned: PreselectedProduct | undefined;
  clearPlan: () => void;
} {
  const [searchParams, setSearchParams] = useSearchParams();
  const planId = searchParams.get("plan");
  const quantity = searchParams.get("quantity") ?? undefined;
  const { data: product } = useQuery({
    queryKey: queryKeys.maker.product(planId ?? ""),
    queryFn: () => makerProductsApi.get(planId as string),
    enabled: planId !== null,
  });
  const planned = useMemo(
    () =>
      product
        ? {
            output_template_id: product.product_template_id,
            name: product.name,
            quantity,
            mode: "planned" as const,
          }
        : undefined,
    [product, quantity],
  );
  return {
    planned,
    clearPlan: () => {
      if (planId !== null) setSearchParams({}, { replace: true });
    },
  };
}
