import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import {
  pricelistApi,
  type PartnerPricelist,
  type PartnerPricelistCreate,
  type PartnerPricelistUpdate,
  type PricelistListParams,
} from "../api/pricelist";

export function usePricelistForPartner(
  partnerId: string,
  params?: PricelistListParams,
) {
  return useModuleQuery<PartnerPricelist[]>("purchase_orders", {
    queryKey: queryKeys.purchaseOrders.pricelistForPartner(partnerId, params),
    queryFn: () => pricelistApi.listForPartner(partnerId, params),
    extraEnabled: Boolean(partnerId),
  });
}

export function usePricelistForTemplate(templateId: string) {
  return useQuery<PartnerPricelist[]>({
    queryKey: queryKeys.purchaseOrders.pricelistForTemplate(templateId),
    queryFn: () => pricelistApi.listForTemplate(templateId),
    enabled: Boolean(templateId),
  });
}

export function useBestPriceForTemplate(templateId: string) {
  return useQuery<PartnerPricelist | null>({
    queryKey: queryKeys.purchaseOrders.pricelistBestForTemplate(templateId),
    queryFn: () => pricelistApi.bestForTemplate(templateId),
    enabled: Boolean(templateId),
  });
}

export function useCreatePricelist() {
  return useAppMutation<PartnerPricelist, PartnerPricelistCreate>(
    pricelistApi.create,
    (qc) => {
      invalidation.purchaseOrders(qc);
    },
  );
}

export function useUpdatePricelist() {
  return useAppMutation<
    PartnerPricelist,
    { id: string; data: PartnerPricelistUpdate }
  >(
    ({ id, data }) => pricelistApi.update(id, data),
    (qc) => {
      invalidation.purchaseOrders(qc);
    },
  );
}

export function useDeletePricelist() {
  return useAppMutation<void, string>(pricelistApi.remove, (qc) => {
    invalidation.purchaseOrders(qc);
  });
}
