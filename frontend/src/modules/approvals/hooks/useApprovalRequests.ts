import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";

import { approvalsApi } from "@/modules/approvals/api/approvals";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";

const requestKeys = {
  all: queryKeys.approvals.requests,
  list: (filters?: {
    target_type?: string;
    status?: string;
    search?: string;
    offset?: number;
    limit?: number;
  }) => [...queryKeys.approvals.requests, "list", filters] as const,
  detail: (id: string) => [...queryKeys.approvals.requests, id] as const,
};

export function useApprovalRequests(
  params?: {
    target_type?: string;
    status?: string;
    search?: string;
    offset?: number;
    limit?: number;
  },
  options?: {
    /**
     * ANDed with the module-enabled check. Name it when the caller holds a
     * better read than this list — the slot's per-target request makes the
     * type-wide fetch (scoped by approvals:read, paginated) pure waste.
     */
    extraEnabled?: boolean;
  },
) {
  return useModuleQuery("approvals", {
    queryKey: requestKeys.list(params),
    queryFn: () => approvalsApi.listRequests(params),
    extraEnabled: options?.extraEnabled,
  });
}

export function useRequestApproval() {
  return useAppMutation(
    ({ targetType, targetId }: { targetType: string; targetId: string }) =>
      approvalsApi.requestApproval(targetType, targetId),
    (qc) => {
      qc.invalidateQueries({ queryKey: requestKeys.all });
      // the documents "Awaiting My Approval" queue renders the same
      // requests — refresh it so the card transitions without a reload.
      qc.invalidateQueries({ queryKey: queryKeys.documents.awaitingApproval });
    },
  );
}

export function useApproveStage() {
  return useAppMutation(
    ({ id, notes }: { id: string; notes?: string }) =>
      approvalsApi.approveStage(id, notes),
    (qc) => {
      qc.invalidateQueries({ queryKey: requestKeys.all });
      // the documents "Awaiting My Approval" queue renders the same
      // requests — refresh it so the card transitions without a reload.
      qc.invalidateQueries({ queryKey: queryKeys.documents.awaitingApproval });
      // A settled request clears its "waiting for your decision" notices
      // on the server — refresh the bell so it stops counting them.
      invalidation.notifications(qc);
    },
  );
}

export function useRejectRequest() {
  return useAppMutation(
    ({ id, notes }: { id: string; notes?: string }) =>
      approvalsApi.rejectRequest(id, notes),
    (qc) => {
      qc.invalidateQueries({ queryKey: requestKeys.all });
      // the documents "Awaiting My Approval" queue renders the same
      // requests — refresh it so the card transitions without a reload.
      qc.invalidateQueries({ queryKey: queryKeys.documents.awaitingApproval });
      // A settled request clears its "waiting for your decision" notices
      // on the server — refresh the bell so it stops counting them.
      invalidation.notifications(qc);
    },
  );
}

export function useCancelRequest() {
  return useAppMutation(
    ({ id }: { id: string }) => approvalsApi.cancelRequest(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: requestKeys.all });
      // the documents "Awaiting My Approval" queue renders the same
      // requests — refresh it so the card transitions without a reload.
      qc.invalidateQueries({ queryKey: queryKeys.documents.awaitingApproval });
      // A settled request clears its "waiting for your decision" notices
      // on the server — refresh the bell so it stops counting them.
      invalidation.notifications(qc);
      // Withdrawing also moves the document the request belonged to (it
      // leaves PENDING_APPROVAL) and its own approval read — without this
      // the card kept the pending state until a reload.
      qc.invalidateQueries({ queryKey: queryKeys.documents.all });
      qc.invalidateQueries({ queryKey: queryKeys.documents.approvalAll });
      // The same for a purchase order: a withdrawn request turns its
      // approval-requirement answer from "an open request" into the verdict
      // on a new one, which the card's Request approval asks with.
      qc.invalidateQueries({ queryKey: queryKeys.purchaseOrders.all });
    },
  );
}
