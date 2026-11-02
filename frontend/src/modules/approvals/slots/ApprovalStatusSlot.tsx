import { InlineQueryError } from "@/components/ui/QueryResult";
import { ApprovalActions } from "@/modules/approvals/components/ApprovalActions";
import { useApprovalRequests } from "@/modules/approvals/hooks/useApprovalRequests";
import { pickLatestRequest } from "@/modules/approvals/lib/pickLatestRequest";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";

export function ApprovalStatusSlot({
  data,
}: {
  data: SlotDataMap["approval_status_badge"];
}) {
  const { targetType, targetId, requestModule } = data;

  // The target module's own read settles which request this target has. The
  // type list stays only for callers that pass no such read — it is scoped by
  // approvals:read, so it cannot see requests raised by somebody else.
  const holdsRequestRead = "approval" in data;

  const {
    data: requests,
    isError,
    error,
    refetch,
  } = useApprovalRequests(
    { target_type: targetType },
    { extraEnabled: !holdsRequestRead },
  );

  // "No request found" is a claim the card acts on (it offers to raise one),
  // so a failed read must not stand in for it.
  if (isError) {
    return <InlineQueryError error={error} onRetry={() => void refetch()} />;
  }

  const matching = (requests?.items ?? []).filter(
    (r) => r.target_id === targetId,
  );

  const latest = holdsRequestRead ? data.approval : pickLatestRequest(matching);

  return (
    <ApprovalActions
      targetType={targetType}
      targetId={targetId}
      requestModule={requestModule}
      requestConsequence={data.requestConsequence}
      approval={latest}
      onApprove={
        data.onApprove
          ? async (request, notes) => {
              // the note typed in the confirm dialog belongs to the
              // module's own approve endpoint — pass it through instead of
              // dropping it at the slot boundary.
              await data.onApprove?.(request.id, notes);
            }
          : undefined
      }
      onRequest={
        data.onRequest
          ? async () => {
              await data.onRequest?.();
            }
          : undefined
      }
      onReject={
        data.onReject
          ? async (request, notes) => {
              await data.onReject?.(request.id, notes);
            }
          : undefined
      }
    />
  );
}
