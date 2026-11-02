import type { ApprovalRequest } from "@/modules/approvals/api/approvals";

/**
 * The request the UI should treat as "the current one" for a target.
 *
 * The requests endpoint does not guarantee a date ordering, so picking the
 * first matching item can surface an older withdrawn request next to a newer
 * one. Newest is selected explicitly by `created_at`.
 */
export function pickLatestRequest(
  requests: ApprovalRequest[],
): ApprovalRequest | null {
  if (requests.length === 0) return null;
  return (
    [...requests].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0] ?? null
  );
}
