import { AlertTriangle, Bell } from "lucide-react";
import { useApprovalRequests } from "@/modules/approvals/hooks/useApprovalRequests";
import { useCanDecideApprovals } from "@/modules/approvals/hooks/useApprovalPermissions";
import { OPEN_APPROVAL_STATES } from "@/modules/approvals/approvalStates";
import type { ActionItem } from "@/lib/moduleRegistry";

export function useApprovalActionItems(): ActionItem[] {
  // The queue counts everything still awaiting a decision. Counting PENDING
  // alone understated it by every request already part-way through a
  // multi-stage workflow, so the badge and the queue disagreed.
  const { data, isError } = useApprovalRequests({
    status: OPEN_APPROVAL_STATES,
  });
  // An action item is a call to act. Without the grant the queue it links to
  // holds nothing this user can decide, so there is no action to call for.
  const canDecide = useCanDecideApprovals();
  if (!canDecide) return [];
  // A failed read is not an empty queue: say the count could not be taken,
  // pointing at the queue that shows the failure in full.
  if (isError) {
    return [
      {
        id: "approvals-unavailable",
        labelKey: "approvals:launcher.actionItems.unavailableLabel",
        icon: AlertTriangle,
        severity: "error",
        linkTo: "/approvals",
      },
    ];
  }
  const count = data?.total ?? 0;
  if (count === 0) return [];
  // The feed owns translation: `labelKey` is a key, not a rendered string, so
  // the count travels as interpolation data and plural forms survive.
  return [
    {
      id: "approvals-pending",
      labelKey: "approvals:launcher.actionItems.pendingLabel",
      labelValues: { count },
      icon: Bell,
      severity: "warning",
      linkTo: `/approvals?status=${OPEN_APPROVAL_STATES}`,
      count,
    },
  ];
}
