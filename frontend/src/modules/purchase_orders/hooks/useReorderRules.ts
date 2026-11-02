import { useAppMutation } from "@/lib/api/mutationFactory";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import {
  reorderRulesApi,
  replenishmentApi,
  type ReorderRule,
  type ReorderRuleCreateInput,
  type ReorderRuleListParams,
  type ReorderRuleUpdate,
  type ReplenishmentAlert,
  type ReplenishmentDraftPosResult,
} from "../api/reorder-rules";

export function useReorderRules(params?: ReorderRuleListParams) {
  return useModuleQuery<ReorderRule[]>("purchase_orders", {
    queryKey: queryKeys.purchaseOrders.reorderRules(params),
    queryFn: () => reorderRulesApi.list(params),
  });
}

export function useCreateReorderRule() {
  return useAppMutation<ReorderRule, ReorderRuleCreateInput>(
    reorderRulesApi.create,
    (qc) => {
      invalidation.purchaseOrders(qc);
    },
  );
}

export function useUpdateReorderRule() {
  return useAppMutation<ReorderRule, { id: string; data: ReorderRuleUpdate }>(
    ({ id, data }) => reorderRulesApi.update(id, data),
    (qc) => {
      invalidation.purchaseOrders(qc);
    },
  );
}

export function useDeleteReorderRule() {
  return useAppMutation<void, string>(reorderRulesApi.remove, (qc) => {
    invalidation.purchaseOrders(qc);
  });
}

export function useReplenishmentAlerts() {
  return useModuleQuery<ReplenishmentAlert[]>("purchase_orders", {
    queryKey: queryKeys.purchaseOrders.replenishmentAlerts(),
    queryFn: () => replenishmentApi.listAlerts(),
  });
}

export function useCreateReplenishmentDraftPos() {
  return useAppMutation<ReplenishmentDraftPosResult, string[]>(
    (reorderRuleIds) => replenishmentApi.createDraftPos(reorderRuleIds),
    (qc) => {
      invalidation.purchaseOrders(qc);
    },
  );
}
