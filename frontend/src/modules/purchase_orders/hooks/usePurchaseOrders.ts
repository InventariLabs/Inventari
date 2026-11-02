import { useQuery, useMutation } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { purchaseOrdersApi } from "@/modules/purchase_orders/api/purchase-orders";
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderUpdate,
  PurchaseOrderListParams,
  PurchaseOrderListResponse,
  POSettings,
  POSettingsUpdate,
} from "@/modules/purchase_orders/types/purchase-orders";
import type { TargetApprovalRequest as ApprovalRequest } from "@/lib/moduleRegistry";
import type { LinkedReceipt } from "@/modules/purchase_orders/api/purchase-orders";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";

export function usePurchaseOrders(params: PurchaseOrderListParams = {}) {
  const queryParams = {
    ...params,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  };
  return useModuleQuery<PurchaseOrderListResponse>("purchase_orders", {
    queryKey: queryKeys.purchaseOrders.list(queryParams),
    queryFn: () => purchaseOrdersApi.getAll(queryParams),
  });
}

export function usePurchaseOrder(id: string) {
  return useQuery<PurchaseOrder>({
    queryKey: queryKeys.purchaseOrders.detail(id),
    queryFn: () => purchaseOrdersApi.getById(id),
    enabled: Boolean(id),
  });
}

export function useLinkedReceipts(poId: string) {
  return useQuery<LinkedReceipt[]>({
    queryKey: queryKeys.purchaseOrders.linkedReceipts(poId),
    queryFn: () => purchaseOrdersApi.getLinkedReceipts(poId),
    enabled: Boolean(poId),
  });
}

export function usePendingQuantities(
  poId: string,
  enabled: boolean,
): Record<string, string> | undefined {
  const { data } = useQuery<Record<string, string>>({
    queryKey: queryKeys.purchaseOrders.pendingQuantities(poId),
    queryFn: () => purchaseOrdersApi.getPendingQuantities(poId),
    enabled: Boolean(poId) && enabled,
    staleTime: 5_000,
  });
  return data;
}

export function useCreatePurchaseOrder() {
  return useAppMutation<PurchaseOrder, PurchaseOrderCreate>(
    purchaseOrdersApi.create,
    (qc) => {
      invalidation.purchaseOrders(qc);
    },
  );
}

export function useUpdatePurchaseOrder() {
  return useAppMutation<
    PurchaseOrder,
    { id: string; data: PurchaseOrderUpdate }
  >(
    ({ id, data }) => purchaseOrdersApi.update(id, data),
    (qc, _, { id }) => {
      invalidation.purchaseOrders(qc, id);
    },
  );
}

export function useConfirmPurchaseOrder() {
  return useAppMutation<PurchaseOrder, string>(
    purchaseOrdersApi.confirm,
    (qc, _, id) => {
      invalidation.purchaseOrders(qc, id);
      // Confirming can raise the order's approval request. The card on the
      // order's page reads the approvals list, and left stale it offered to
      // request an approval that had just been requested.
      invalidation.approvals(qc);
    },
  );
}

export function useCancelPurchaseOrder() {
  return useAppMutation<PurchaseOrder, string>(
    purchaseOrdersApi.cancel,
    (qc, _, id) => {
      invalidation.purchaseOrders(qc, id);
      // Cancelling withdraws the order's open approval request, which marks
      // the "waiting for your decision" notice read.
      invalidation.notifications(qc);
    },
  );
}

export function useSendPoEmail() {
  return useMutation<
    { status: string; message: string },
    Error,
    { poId: string; lang?: string }
  >({
    mutationFn: ({ poId, lang }) => purchaseOrdersApi.sendEmail(poId, lang),
  });
}

export function useDownloadPoPdf() {
  return useMutation<Blob, Error, { poId: string; lang?: string }>({
    mutationFn: ({ poId, lang }) => purchaseOrdersApi.getPdf(poId, lang),
  });
}

// ── Approval ─────────────────

export function usePOSettings() {
  return useQuery<POSettings>({
    queryKey: queryKeys.purchaseOrders.settings(),
    queryFn: () => purchaseOrdersApi.getPOSettings(),
  });
}

export function useUpdatePOSettings() {
  return useAppMutation<POSettings, POSettingsUpdate>(
    purchaseOrdersApi.updatePOSettings,
    (qc) => {
      qc.invalidateQueries({
        queryKey: queryKeys.purchaseOrders.settings(),
      });
    },
  );
}

/**
 * The approval requests raised on purchase orders, read under the key the
 * approvals module's own list uses for the same filter — one cache entry,
 * and `invalidation.approvals` refreshes both readers.
 */
export function usePOApprovalRequests() {
  return useModuleQuery("approvals", {
    queryKey: [
      ...queryKeys.approvals.requests,
      "list",
      { target_type: "purchase_order" },
    ] as const,
    queryFn: () => purchaseOrdersApi.listApprovalRequests(),
  });
}

/**
 * Whether a request on a purchase order would land — the server's answer,
 * not the workflow list's, which is filtered by ``approvals:read`` and so
 * answers nothing to the role that composes a request.
 *
 * ``undefined`` means the question cannot be answered yet (in flight, an
 * error, the module off). Callers treat only ``false`` as "the engine would
 * refuse a request" and leave every other answer to the API.
 */
export function usePOApprovalWorkflowConfigured(): boolean | undefined {
  const approvalsEnabled = useEnabledModulesOptional().includes("approvals");
  const { data, isSuccess } = useQuery({
    queryKey: queryKeys.approvals.workflowConfigured("purchase_order"),
    queryFn: () => purchaseOrdersApi.getApprovalWorkflowConfigured(),
    enabled: approvalsEnabled,
  });
  if (!isSuccess) return undefined;
  return data.configured;
}

/**
 * What confirming this draft would do for the person asking, and whether
 * anybody could decide the approval it would start — the server's answer, from
 * the rule the confirmation itself obeys. ``undefined`` with the approvals
 * module off, and for an order past its draft: nothing to ask then.
 */
export function usePOApprovalRequirement(
  po: Pick<PurchaseOrder, "id" | "status"> | null,
) {
  const approvalsEnabled = useEnabledModulesOptional().includes("approvals");
  const { data } = useQuery({
    queryKey: queryKeys.purchaseOrders.approvalRequirement(po?.id ?? ""),
    queryFn: () => purchaseOrdersApi.getApprovalRequirement(po?.id ?? ""),
    enabled: approvalsEnabled && po?.status === "DRAFT",
    staleTime: 15_000,
  });
  return data;
}

export function useRequestPOApproval() {
  return useAppMutation<ApprovalRequest, string>(
    purchaseOrdersApi.requestApproval,
    (qc, _, poId) => {
      invalidation.purchaseOrders(qc, poId);
      // The approval slot reads the shared approvals requests list, so a
      // request created from the PO header must refresh it too.
      invalidation.approvals(qc);
    },
  );
}

export function useApprovePO() {
  return useAppMutation<ApprovalRequest, { poId: string; notes?: string }>(
    ({ poId, notes }) => purchaseOrdersApi.approvePO(poId, notes),
    (qc, _, { poId }) => {
      invalidation.purchaseOrders(qc, poId);
      invalidation.approvals(qc);
    },
  );
}

export function useRejectPO() {
  return useAppMutation<ApprovalRequest, { poId: string; notes?: string }>(
    ({ poId, notes }) => purchaseOrdersApi.rejectPO(poId, notes),
    (qc, _, { poId }) => {
      invalidation.purchaseOrders(qc, poId);
      invalidation.approvals(qc);
    },
  );
}
