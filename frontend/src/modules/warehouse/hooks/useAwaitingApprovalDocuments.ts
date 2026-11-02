import {
  useQuery,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { useCallback } from "react";

import { queryKeys } from "@/hooks/queries/keys";
import { documentsApi } from "@/modules/warehouse/api/documents";

const DEFAULT_LIMIT = 50;

/**
 * Fetch the documents awaiting the current user's approval.
 *
 * Pass ``enabled: false`` when the approvals module is disabled for the
 * org (e.g. from the nav badge) so the query does not fire uselessly —
 * the awaiting-approval endpoint returns an empty list when approvals is
 * off, but skipping the request entirely is cheaper and avoids QueryClient
 * noise. Mirrors the ``useDocumentApproval`` gating pattern.
 *
 * ``offset``/``limit`` drive server-side pagination. The query key always
 * includes both (defaulting to 0/50), so the nav badge and the queue page
 * at page 1 share the same cache entry.
 */
export function useAwaitingApprovalDocuments(options?: {
  enabled?: boolean;
  offset?: number;
  limit?: number;
}) {
  const queryClient = useQueryClient();
  const offset = options?.offset ?? 0;
  const limit = options?.limit ?? DEFAULT_LIMIT;

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.documents.awaitingApproval,
    });
  }, [queryClient]);

  const query = useQuery({
    queryKey: queryKeys.documents.awaitingApprovalPage(offset, limit),
    queryFn: () => documentsApi.listAwaitingMyApproval({ offset, limit }),
    enabled: options?.enabled ?? true,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

  return Object.assign(query, { invalidate });
}
