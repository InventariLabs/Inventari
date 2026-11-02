import { useAppMutation } from "@/lib/api/mutationFactory";
import { useQuery } from "@tanstack/react-query";
import { documentApprovalApi } from "@/modules/warehouse/api/documents";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";

export function useApproveDocument() {
  return useAppMutation(
    ({ docId, notes }: { docId: string; notes?: string }) =>
      documentApprovalApi.approve(docId, notes),
    (qc, _data, variables) => {
      invalidation.documents(qc, variables.docId);
      invalidation.approvals(qc);
    },
  );
}

export function useRequestDocumentApproval() {
  return useAppMutation(
    ({ docId, notes }: { docId: string; notes?: string }) =>
      documentApprovalApi.requestApproval(docId, notes),
    (qc, _data, variables) => {
      invalidation.documents(qc, variables.docId);
      invalidation.approvals(qc);
    },
  );
}

export function useRejectDocument() {
  return useAppMutation(
    ({ docId, notes }: { docId: string; notes?: string }) =>
      documentApprovalApi.reject(docId, notes),
    (qc, _data, variables) => {
      invalidation.documents(qc, variables.docId);
      invalidation.approvals(qc);
    },
  );
}

/**
 * Fetch the latest approval request for a document.
 *
 * Pass ``enabled: false`` when the approvals module is disabled for the
 * org — otherwise the query would fire and the response is meaningless.
 * This is also the standard React Query guard pattern that keeps the
 * detail page rendering even when the approvals module is unavailable
 * (no ModulesProvider, approvals off, etc.).
 */
export function useDocumentApproval(
  docId: string | undefined,
  options?: { enabled?: boolean },
) {
  const enabled = (options?.enabled ?? true) && Boolean(docId);
  return useQuery({
    queryKey: queryKeys.documents.approval(docId ?? ""),
    queryFn: () => documentApprovalApi.get(docId ?? ""),
    enabled,
    staleTime: 15_000,
  });
}

/**
 * Whether confirming this document would send it to the approval queue.
 *
 * Asked of the backend because the rule is the backend's: the profile's
 * listed types and threshold — and, when the profile names neither, an
 * active approval workflow for documents. The page used to recompute part
 * of it from the workflow list and the profile — a second definition that
 * could name a consequence the server would not carry out.
 *
 * Pass ``enabled: false`` when the approvals module is disabled for the org,
 * as the approval fetch beside it does: nothing can be queued then, and the
 * request would be a wasted round-trip.
 */
export function useDocumentApprovalRequirement(
  docId: string | undefined,
  options?: { enabled?: boolean },
) {
  const enabled = (options?.enabled ?? true) && Boolean(docId);
  return useQuery({
    queryKey: queryKeys.documents.approvalRequirement(docId ?? ""),
    queryFn: () => documentApprovalApi.getRequirement(docId ?? ""),
    enabled,
    staleTime: 15_000,
  });
}
