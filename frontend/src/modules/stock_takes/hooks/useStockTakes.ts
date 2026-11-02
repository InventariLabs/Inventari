import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { stockTakesApi } from "@/modules/stock_takes/api/stock-takes";
import type {
  StockTake,
  StockTakeCreateInput,
  StockTakeItem,
  StockTakeListResponse,
  StockTakeReport,
  StockTakeStatus,
  ShelfClosed,
  LocationCountState,
} from "@/modules/stock_takes/types/stock-takes";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { invalidation } from "@/lib/api/invalidation";

export function useStockTakes(
  statusFilter?: StockTakeStatus | "",
  pagination?: { offset?: number; limit?: number },
) {
  return useModuleQuery<StockTakeListResponse>("stock_takes", {
    queryKey: [...queryKeys.stockTakes.list(statusFilter), pagination ?? {}],
    queryFn: () =>
      stockTakesApi.getAll({
        status_filter: statusFilter || undefined,
        offset: pagination?.offset,
        limit: pagination?.limit,
      }),
    placeholderData: pagination ? keepPreviousData : undefined,
  });
}

export function useStockTake(id: string | undefined) {
  return useQuery<StockTake>({
    queryKey: queryKeys.stockTakes.detail(id!),
    queryFn: () => stockTakesApi.getById(id!),
    enabled: !!id,
  });
}

export function useStockTakeReport(id: string | undefined) {
  return useModuleQuery<StockTakeReport>("stock_takes", {
    queryKey: queryKeys.stockTakes.report(id!),
    queryFn: () => stockTakesApi.getReport(id!),
    extraEnabled: !!id,
  });
}

/** When each location was last counted, and which are being counted now. */
export function useLocationCountStates() {
  return useModuleQuery<LocationCountState[]>("stock_takes", {
    queryKey: queryKeys.stockTakes.locations,
    queryFn: () => stockTakesApi.getLocationStates(),
  });
}

export function useCreateStockTake() {
  const { t } = useTranslation(["stock_takes"]);
  return useAppMutation<StockTake, StockTakeCreateInput>(
    (data) => stockTakesApi.create(data),
    (qc) => {
      invalidation.stockTakes(qc);
    },
    { errorFallback: t("errors.createFailed") },
  );
}

export function useDeleteStockTake() {
  const { t } = useTranslation(["stock_takes"]);
  return useAppMutation<void, string>(
    (id) => stockTakesApi.delete(id),
    (qc) => {
      invalidation.stockTakes(qc);
    },
    { errorFallback: t("errors.deleteFailed") },
  );
}

export function useAddStockTakeItem(stockTakeId: string | undefined) {
  const { t } = useTranslation(["stock_takes"]);
  return useAppMutation<
    StockTakeItem,
    { itemId: string; quantity: number; notes?: string; shelfId?: string }
  >(
    ({ itemId, quantity, notes, shelfId }) =>
      stockTakesApi.addItem(stockTakeId!, {
        item_id: itemId,
        counted_quantity: quantity,
        notes: notes || null,
        ...(shelfId ? { location_id: shelfId } : {}),
      }),
    (qc) => {
      invalidation.stockTakes(qc, stockTakeId);
    },
    { errorFallback: t("errors.addItemFailed") },
  );
}

export function useCountStockTakeItem(stockTakeId: string | undefined) {
  const { t } = useTranslation(["stock_takes"]);
  return useAppMutation<
    StockTakeItem,
    {
      stockTakeItemId: string;
      quantity: number;
      notes?: string;
      discrepancy_reason_code?: string | null;
      discrepancy_reason?: string | null;
    }
  >(
    ({
      stockTakeItemId,
      quantity,
      notes,
      discrepancy_reason_code,
      discrepancy_reason,
    }) =>
      stockTakesApi.countItem(stockTakeId!, stockTakeItemId, {
        counted_quantity: quantity,
        notes: notes || null,
        discrepancy_reason_code: discrepancy_reason_code ?? null,
        discrepancy_reason: discrepancy_reason ?? null,
      }),
    (qc) => {
      invalidation.stockTakes(qc, stockTakeId);
    },
    { errorFallback: t("errors.saveFailed") },
  );
}

export function useRequestRecount(stockTakeId: string | undefined) {
  const { t } = useTranslation(["stock_takes"]);
  // The first answer to a difference nobody expected is to count it a second
  // time, not to approve it.
  return useAppMutation<StockTakeItem, { stockTakeItemId: string }>(
    ({ stockTakeItemId }) =>
      stockTakesApi.requestRecount(stockTakeId!, stockTakeItemId),
    (qc) => {
      invalidation.stockTakes(qc, stockTakeId);
    },
    { errorFallback: t("errors.recountFailed") },
  );
}

export function useCloseStockTakeLocation(stockTakeId: string | undefined) {
  const { t } = useTranslation(["stock_takes"]);
  return useAppMutation<ShelfClosed, string>(
    (locationId) => stockTakesApi.closeLocation(stockTakeId!, locationId),
    (qc) => {
      invalidation.stockTakes(qc, stockTakeId);
    },
    { errorFallback: t("errors.saveFailed") },
  );
}

export function useCompleteStockTake(stockTakeId: string | undefined) {
  const { t } = useTranslation(["stock_takes"]);
  // `forceOverCap` is the supervisor's explicit acceptance of counts far
  // above the system stock; without it the server refuses the whole posting
  // rather than quietly writing a smaller number.
  return useAppMutation<
    StockTakeReport,
    { forceOverCap?: boolean; forceOverTolerance?: boolean } | void
  >(
    (vars) =>
      stockTakesApi.complete(
        stockTakeId!,
        true,
        undefined,
        Boolean(vars && vars.forceOverCap),
        Boolean(vars && vars.forceOverTolerance),
      ),
    (qc) => {
      invalidation.stockTakes(qc, stockTakeId);
    },
    { errorFallback: t("errors.completeFailed") },
  );
}

export function useCancelStockTake() {
  const { t } = useTranslation(["stock_takes"]);
  return useAppMutation<unknown, string>(
    (id) => stockTakesApi.cancel(id),
    (qc) => {
      invalidation.stockTakes(qc);
    },
    { errorFallback: t("errors.cancelFailed") },
  );
}
