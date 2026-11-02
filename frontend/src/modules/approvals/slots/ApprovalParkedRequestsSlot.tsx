import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AlertTriangle, ExternalLink } from "lucide-react";

import { Card, CardContent } from "@/components/ui/Card";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { ApprovalDeadEndNotice } from "@/modules/approvals/components/ApprovalDeadEndNotice";
import { useApprovalRequests } from "@/modules/approvals/hooks/useApprovalRequests";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";

/**
 * The requests parked at a stage nobody can decide on.
 *
 * They are not in the queue — there is nobody whose queue they could be in —
 * so without this section they read as "nothing waiting". Each names the
 * record and carries the dead-end notice with the moves open to the one
 * reading it: withdraw for the requester, give the access for an
 * administrator, whom to ask for everybody else.
 *
 * The list is scoped by the server: everyone meets their own parked
 * requests, and an `approvals:read` grant meets the organization's. A failed
 * read must not stand in for "none are parked".
 */
export function ApprovalParkedRequestsSlot({
  data: { targetType, targetHref },
}: {
  data: SlotDataMap["approval_parked_requests"];
}) {
  const { t } = useTranslation("approvals");
  const { data, isError, error, refetch } = useApprovalRequests({
    target_type: targetType,
    status: "PENDING,IN_PROGRESS",
    limit: 100,
  });
  const parked = useMemo(
    () => (data?.items ?? []).filter((request) => request.solvable === false),
    [data],
  );

  if (isError) {
    return <InlineQueryError error={error} onRetry={() => void refetch()} />;
  }
  if (parked.length === 0) return null;

  return (
    <Card className="border-amber-300 dark:border-amber-800">
      <CardContent className="p-4">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-on">
          <AlertTriangle size={16} className="text-amber-600" />
          {t("documentQueue.parkedTitle")}
        </p>
        <p className="mt-1 text-xs text-on-secondary">
          {t("documentQueue.parkedSubtitle")}
        </p>
        <ul className="mt-3 space-y-2">
          {parked.map((request) => (
            <li key={request.id} className="space-y-1.5">
              <span className="flex flex-wrap items-center gap-2 text-sm">
                <Link
                  to={targetHref(request.target_id)}
                  className="inline-flex items-center gap-1.5 font-semibold text-on underline-offset-4 hover:underline"
                >
                  {request.target_summary?.number ?? request.target_id}
                  <ExternalLink size={13} className="text-on-muted" />
                </Link>
                {request.created_by_name && (
                  <span className="text-xs font-normal text-on-muted">
                    {request.created_by_name} · {t("documentQueue.requester")}
                  </span>
                )}
              </span>
              <ApprovalDeadEndNotice subject={request} request={request} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
