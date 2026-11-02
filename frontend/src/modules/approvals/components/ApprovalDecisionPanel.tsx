import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import {
  ApprovalDecisionButtons,
  TERMINAL_STATUSES,
} from "./ApprovalDecisionButtons";
import { ApprovalDeadEndNotice } from "./ApprovalDeadEndNotice";
import {
  useCanDecideApprovals,
  useHasApprovalAction,
} from "@/modules/approvals/hooks/useApprovalPermissions";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";
import { formatDate, formatTime } from "@/utils/formatters";

function isTerminalApproval(status: ApprovalRequest["status"]): boolean {
  return TERMINAL_STATUSES.has(status);
}

/** The decision row this request was resolved by, if it recorded one. */
function findDecision(
  request: ApprovalRequest,
): ApprovalRequest["decisions"][number] | null {
  // Decisions arrive in stage order, and the stage that settled the request
  // is the last one to decide: a first match named stage one's approver on
  // a two-stage approval. A withdrawn request records no decision of its
  // own, so the fallback names the last stage that did decide.
  const reversed = [...request.decisions].reverse();
  const decided =
    reversed.find((d) => d.status === request.status) ??
    reversed.find(
      (d) =>
        (d.status === "APPROVED" || d.status === "REJECTED") && d.decided_at,
    );
  return decided && decided.decided_at ? decided : null;
}

/** Post-decision summary — replaces the buttons in the exact same spot. */
function DecisionInfo({
  decided,
}: {
  decided: NonNullable<ReturnType<typeof findDecision>>;
}) {
  const { t } = useTranslation("approvals");

  const dateLabel = formatDate(decided.decided_at as string);
  const timeLabel = formatTime(decided.decided_at as string);

  return (
    <div className="rounded-md bg-surface-inset/60 px-3 py-2 text-xs text-on-secondary">
      <div className="font-medium text-on">
        {decided.status === "APPROVED"
          ? t("dashboard.decision.approvedBy")
          : decided.status === "REJECTED"
            ? t("dashboard.decision.rejectedBy")
            : t("dashboard.decision.decidedBy")}
        {decided.approver_name ? ` ${decided.approver_name}` : ""}
      </div>
      <div className="text-on-muted">
        {dateLabel} {timeLabel}
      </div>
    </div>
  );
}

interface ApprovalDecisionPanelProps {
  approval: ApprovalRequest;
  /** Overrides routing through the document-specific endpoints. */
  onApprove?: (approval: ApprovalRequest, notes?: string) => Promise<void>;
  onReject?: (approval: ApprovalRequest, notes: string) => Promise<void>;
  className?: string;
}

/**
 * the one decision block for every screen that lets a user act on
 * an approval — "YOUR ACTION" while open, "DECISION" after resolution, in
 * the same spot. Used by /approvals, /warehouse/approvals and (via
 * ApprovalActions) the document detail page.
 */
export function ApprovalDecisionPanel({
  approval,
  onApprove,
  onReject,
  className,
}: ApprovalDecisionPanelProps) {
  const { t } = useTranslation("approvals");
  const terminal = isTerminalApproval(approval.status);
  // "Your Action" over a block with no action in it is a promise the API
  // will not keep — a reader without the grant gets the state instead.
  const hasAction = useHasApprovalAction(approval);
  const decided = terminal ? findDecision(approval) : null;
  const canDecideGrant = useCanDecideApprovals();

  // "Awaiting Decision" alone says nothing about why the reader cannot act.
  // Name the reason: a missing grant, or a stage waiting on someone else.
  // (A requester never reaches this branch — they keep the withdraw action.)
  const awaitingMessage = !canDecideGrant
    ? t("request.noPermissionToDecide")
    : t("request.awaitingApprover");

  // A withdrawn request records no decision, and the heading alone
  // was rendering as an empty "DECISION" section. The status badge on the
  // card already states the outcome, so the whole block goes.
  if (terminal && !decided) {
    return null;
  }

  const heading = terminal
    ? t("dashboard.section.decision")
    : hasAction
      ? t("dashboard.section.yourAction")
      : t("dashboard.section.awaitingDecision");

  return (
    /* label and actions share one row from `sm` up — the block used
       to stack a heading over three full-width buttons, which cost the card
       height it did not need and made Approve and Reject read as two equal
       options. Below `sm` it stacks, where a thumb needs the width. */
    <div className={cn("flex flex-col gap-2", className)}>
      {/* Above the row, not inside it: a dead end is about the request, and
          the row is about who may act on it. */}
      <ApprovalDeadEndNotice subject={approval} request={approval} />
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
          {heading}
        </p>
        {decided ? (
          <DecisionInfo decided={decided} />
        ) : hasAction ? (
          <ApprovalDecisionButtons
            approval={approval}
            fullWidth
            onApprove={onApprove}
            onReject={onReject}
          />
        ) : (
          <p className="text-xs text-on-muted">{awaitingMessage}</p>
        )}
      </div>
    </div>
  );
}
