import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { productionApi } from "@/modules/maker/api/production";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import { useAppMutation } from "@/lib/api/mutationFactory";
import type {
  ProductionOrder,
  ProductionOrderComplete,
  ProductionOrderCreateInput,
  ProductionOrderUpdate,
  ProductionStatus,
} from "@/modules/maker/types/maker";

interface ListParams {
  output_template_id?: string;
  status?: ProductionStatus;
  sort?: string;
  date_from?: string;
  date_to?: string;
  skip?: number;
  limit?: number;
}

export function useProductionOrders(params?: ListParams) {
  return useQuery({
    queryKey: queryKeys.maker.productionList(params),
    queryFn: () => productionApi.list(params),
    placeholderData: (prev) => prev,
  });
}

export function useProductionOrder(orderId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maker.productionDetail(orderId ?? ""),
    queryFn: () => productionApi.get(orderId as string),
    enabled: !!orderId,
  });
}

export function useOrderStockMoves(orderId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maker.productionStockMoves(orderId),
    queryFn: () => productionApi.getStockMoves(orderId as string),
    enabled: !!orderId,
  });
}

export function useCreateProductionOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ProductionOrderCreateInput) =>
      productionApi.create(data),
    onSuccess: () => {
      invalidation.maker(queryClient);
    },
  });
}

/** The production sheet's live preview; idle until the form names a run. */
export function useProductionPreview(
  payload: ProductionOrderCreateInput | null,
) {
  return useQuery({
    queryKey: queryKeys.maker.productionPreview(payload),
    queryFn: () => productionApi.preview(payload as ProductionOrderCreateInput),
    enabled: payload !== null,
    placeholderData: (prev) => prev,
  });
}

export function useRecordMadeProduction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ProductionOrderCreateInput) =>
      productionApi.recordMade(data),
    onSuccess: (order: ProductionOrder) => {
      invalidation.maker(queryClient, order.id);
      // The run wrote stock, like a completion does.
      invalidation.items(queryClient);
      queryClient.invalidateQueries({ queryKey: queryKeys.stockQuants.all });
    },
  });
}

export function useAddShortagesToShoppingList() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ProductionOrderCreateInput) =>
      productionApi.shortagesToShoppingList(data),
    onSuccess: () => {
      invalidation.shoppingLists(queryClient);
    },
  });
}

export function useUpdateProductionOrder(errorFallback?: string) {
  return useAppMutation<
    ProductionOrder,
    { orderId: string; data: ProductionOrderUpdate }
  >(
    ({ orderId, data }) => productionApi.update(orderId, data),
    (qc, order) => {
      invalidation.maker(qc, order.id);
    },
    { errorFallback },
  );
}

export function useDuplicateProductionOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => productionApi.duplicate(orderId),
    onSuccess: () => {
      invalidation.maker(queryClient);
    },
  });
}

export function useCompleteProduction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      orderId,
      data,
    }: {
      orderId: string;
      data?: ProductionOrderComplete;
    }) => productionApi.complete(orderId, data),
    onSuccess: (order: ProductionOrder) => {
      invalidation.maker(queryClient, order.id);
      // Completing a run writes stock, so the stock screens are invalidated
      // through the same helper the document paths use. A fourth line here
      // addressed ["valuation"] — a key no query in this application has
      // ever used, so it invalidated nothing and read like cover for the
      // valuation figures it could not refresh.
      invalidation.items(queryClient);
      queryClient.invalidateQueries({ queryKey: queryKeys.stockQuants.all });
    },
  });
}

export function useCancelProduction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, reason }: { orderId: string; reason?: string }) =>
      productionApi.cancel(orderId, reason ? { reason } : undefined),
    onSuccess: (order: ProductionOrder) => {
      invalidation.maker(queryClient, order.id);
    },
  });
}

/** Take a completed run back: the ingredients return, the output leaves. */
export function useReverseProduction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => productionApi.reverse(orderId),
    onSuccess: (order: ProductionOrder) => {
      invalidation.maker(queryClient, order.id);
      // It writes stock as completing did, so the same screens refresh.
      invalidation.items(queryClient);
      queryClient.invalidateQueries({ queryKey: queryKeys.stockQuants.all });
    },
  });
}

/** Monthly financial result aggregation. */
export function useMakerMonthlyResult(months = 6) {
  return useQuery({
    queryKey: queryKeys.maker.monthlyResult(months),
    queryFn: () => productionApi.monthlyResult(months),
    placeholderData: (prev) => prev,
  });
}
