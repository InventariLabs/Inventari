/**
 * Who may act on an approval, asked once and answered the same way on every
 * screen.
 *
 * The API enforces `approvals:approve` on /approve and /reject,
 * `approvals:configure` on workflow writes, and filters the workflow list
 * by `approvals:read`. The UI used to offer all of it to everyone: a user
 * without the grant saw Approve, clicked it, and learned about the rule
 * from a 403 toast. These hooks put the same rule in front of the button.
 *
 * The permission keys match `backend/app/modules/approvals/manifest.json` —
 * the one place they are declared — and reach the browser through the set
 * GET /auth/me returns.
 */
import { useHasPermission } from "@/hooks/useHasPermission";
import { useAuthStore } from "@/store/authStore";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";

/** Approve or reject a pending request. */
export function useCanDecideApprovals(): boolean {
  return useHasPermission("approvals:approve");
}

/**
 * Whether this user may decide on *this* request — the grant plus everything
 * only the server knows: that nobody approves their own request unless the
 * organization allows it, and that a named stage is exclusive.
 *
 * The queue used to ask the grant alone, so a requester saw a live Approve
 * on their own document and learned the rule from a 409.
 */
export function useCanDecideOnApproval(
  approval: ApprovalRequest | null | undefined,
): boolean {
  const canDecide = useCanDecideApprovals();
  if (!approval) return false;
  // The server's verdict already includes delegation — a person named on the
  // stage the request sits at decides with the read grant alone — and the
  // own-request rule. The local grant answers only when the server did not
  // name a viewer (null), which is the legacy shape.
  if (approval.viewer_can_decide === true) return true;
  return canDecide && approval.viewer_can_decide !== false;
}

/** Create, edit or delete a workflow. */
export function useCanConfigureWorkflows(): boolean {
  return useHasPermission("approvals:configure");
}

/**
 * Read the workflow definitions. ``GET /approvals/workflows`` answers a
 * role holding neither this grant nor the configure one with a filtered
 * 200 — an empty list that says nothing about whether the organization
 * has workflows at all. Screens drawing conclusions from that list ask
 * here first, so "no workflows configured" is only ever claimed by an
 * account that can actually see the list.
 */
export function useCanReadWorkflows(): boolean {
  const canRead = useHasPermission("approvals:read");
  const canConfigure = useHasPermission("approvals:configure");
  return canRead || canConfigure;
}

/**
 * Withdrawing is not a decision — the requester takes back their own still-open
 * request, which is why /cancel carries no permission check. Someone without
 * `approvals:approve` keeps this action.
 */
export function canWithdrawApproval(
  approval: ApprovalRequest,
  currentUserId: string | undefined,
): boolean {
  return (
    !!currentUserId &&
    approval.created_by === currentUserId &&
    (approval.status === "PENDING" || approval.status === "IN_PROGRESS")
  );
}

/**
 * Whether this user has anything to do with this request right now. Screens
 * use it to label the block honestly: "Your Action" only when there is one.
 *
 * Takes a nullable request so callers can ask before their own early returns —
 * a hook cannot be called conditionally.
 */
export function useHasApprovalAction(
  approval: ApprovalRequest | null | undefined,
): boolean {
  const canDecide = useCanDecideOnApproval(approval);
  const currentUserId = useAuthStore((state) => state.user?.id);

  if (!approval) return false;

  return canDecide || canWithdrawApproval(approval, currentUserId);
}
