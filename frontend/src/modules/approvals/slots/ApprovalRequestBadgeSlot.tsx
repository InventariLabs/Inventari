import { ApprovalBadge } from "@/modules/approvals/components/ApprovalBadge";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";

export function ApprovalRequestBadgeSlot({
  data,
}: {
  data: SlotDataMap["approval_request_badge"];
}) {
  return <ApprovalBadge status={data.status} />;
}
