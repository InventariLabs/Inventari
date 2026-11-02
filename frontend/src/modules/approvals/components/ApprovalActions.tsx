import { useState } from "react";
import { AUTO_PASSED_NOTE_PREFIX } from "./ApprovalStageStepper";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCheck, Send, Clock, Users } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { extractApiError } from "@/lib/errors";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ApprovalBadge } from "./ApprovalBadge";
import { ApprovalDeadEndNotice } from "./ApprovalDeadEndNotice";
import { ApprovalDecisionButtons } from "./ApprovalDecisionButtons";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";
import { useRequestApproval } from "@/modules/approvals/hooks/useApprovalRequests";
import {
  useCanConfigureWorkflows,
  useHasApprovalAction,
} from "@/modules/approvals/hooks/useApprovalPermissions";
import { useIsWorkflowConfigured } from "@/modules/approvals/hooks/useApprovalWorkflows";
import { useOrgMembers } from "@/modules/approvals/hooks/useOrgMembers";
import { useAuthStore } from "@/store/authStore";
import { formatDate } from "@/utils/helpers";
import { stageName } from "@/modules/approvals/workflowStages";

interface ResolvedRequestProps {
  status: string;
  /** Why it came back — the rejection reason, or when it was withdrawn. */
  note?: string | null;
  /**
   * The way back, when there is one — a `RequestAffordance`, which answers
   * for itself: the button, the missing-workflow notice, or nothing.
   */
  request?: React.ReactNode;
}

/**
 * A request that ended without approval, plus the way back.
 *
 * Rejected and withdrawn requests leave the document exactly where it is —
 * a withdrawal by design, since taking back your own request is not a
 * decision about the document. Both states therefore read the same: what
 * happened, and one button to send it for approval again.
 */
function ResolvedRequest({ status, note, request }: ResolvedRequestProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <ApprovalBadge status={status} />
        {request}
      </div>
      {note && <p className="text-xs text-on-muted">{note}</p>}
    </div>
  );
}

/**
 * The refusal said before the click, for the state that greets every
 * organization the day it enables the module: approvals on, no workflow
 * configured. The engine's sentence — "No active approval workflow is
 * configured for this action" — is a good one; what was wrong was its order,
 * arriving only after the button had been pressed. This says the same thing
 * where the button stood and, for an account that may configure workflows,
 * points at the screen where one is created.
 */
function MissingWorkflowNotice() {
  const { t } = useTranslation("approvals");
  const canConfigure = useCanConfigureWorkflows();
  return (
    <div
      role="note"
      className="flex items-start gap-2 rounded-md bg-amber-100 px-3 py-2 text-xs text-on-warning"
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <div className="flex flex-col gap-1">
        {/* No target label in the sentence: a title-cased word mid-sentence
            read "for Document", and the card already stands on the record
            the request would be about. */}
        <p>{t("request.noWorkflow")}</p>
        {canConfigure && (
          <Link
            to="/approvals/workflows"
            className="font-medium underline hover:no-underline"
          >
            {t("request.configureWorkflow")}
          </Link>
        )}
      </div>
    </div>
  );
}

interface ApprovalActionsProps {
  targetType: string;
  targetId: string;
  approval: ApprovalRequest | null | undefined;
  /**
   * What raising a request will do to the target's state. When the caller
   * names one, the button asks first with that sentence — a request that
   * takes a confirmed document back to the approval queue is a state
   * change, and one silent click is how an approved document got
   * reopened. An unnamed consequence means the request only asks.
   */
  requestConsequence?: string;
  onApprove?: (approval: ApprovalRequest, notes?: string) => Promise<void>;
  /**
   * Override the default request-approval mutation (generic
   * ``POST /approvals/requests``). Target modules that must transition
   * entity state on request (e.g. documents park in PENDING_APPROVAL)
   * should provide this adapter.
   */
  onRequest?: () => Promise<void>;
  /**
   * The module whose write right raising this request answers to. The
   * generic endpoint checks ``approvals:write``; a target module's proxy
   * (documents, purchase_orders) sits behind that module's own router
   * guard instead, so the adapter providers name their module here. The
   * button is hidden from an account holding neither.
   */
  requestModule?: string;
  /**
   * Override the default reject mutation, forwarded to
   * ``ApprovalDecisionButtons``. See its ``onReject`` docstring for why
   * document rejects must route through the document-specific endpoint.
   */
  onReject?: (approval: ApprovalRequest, notes: string) => Promise<void>;
}

/**
 * The one button that sends a request. Nothing to show for an account the
 * endpoint would refuse — the refusal is the reason the button is gone, so
 * the component renders none rather than one that fails on click. When the
 * request does more than ask — the caller names what it does to the
 * target's state — the click is put through that sentence first.
 */
function RequestApprovalButton({
  canRequest,
  consequence,
  onClick,
  isRequesting,
}: {
  canRequest: boolean;
  consequence?: string;
  onClick: () => void;
  isRequesting: boolean;
}) {
  const { t } = useTranslation("approvals");
  const [confirmOpen, setConfirmOpen] = useState(false);
  if (!canRequest) return null;
  return (
    <div className="flex items-center gap-2">
      {/* Outline, not primary: the document's own action bar already owns
          the primary on this screen. A document exists to be executed;
          approval is an optional gate on the way, not the goal. */}
      <Button
        variant="outline"
        size="sm"
        leftIcon={<Send size={16} />}
        onClick={() => (consequence ? setConfirmOpen(true) : onClick())}
        isLoading={isRequesting}
      >
        {t("request.requestApproval")}
      </Button>
      {consequence && (
        <ConfirmDialog
          open={confirmOpen}
          title={t("request.requestConfirmTitle")}
          message={consequence}
          confirmLabel={t("request.requestConfirmLabel")}
          onConfirm={onClick}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * The whole "may I ask for approval, and would it land anywhere?" question
 * in one place: the button, the notice that stands where it would have
 * stood, or nothing at all.
 *
 * The engine refuses a request when no active workflow exists for the
 * target type, so that read belongs in front of the button, not after it.
 * `false` is the conclusion; `undefined` (still loading, no read right, an
 * error) leaves the API the last word — the list is filtered by the read
 * grant, and an empty one says nothing to an account that cannot see it.
 */
function RequestAffordance({
  targetType,
  canRequest,
  consequence,
  onClick,
  isRequesting,
}: {
  targetType: string;
  canRequest: boolean;
  consequence?: string;
  onClick: () => void;
  isRequesting: boolean;
}) {
  const workflowConfigured = useIsWorkflowConfigured(targetType);
  // An account the endpoint would refuse meets no button and no notice: the
  // missing permission is the reason the button is gone, and a warning about
  // a request this reader cannot make is noise on their screen.
  if (!canRequest) return null;
  if (workflowConfigured === false) {
    // A request that changes the target's state is the exceptional path —
    // sending a confirmed document back — not the flow's next step. With no
    // workflow to land in there is nothing to offer and nothing to warn
    // about, so a missing-workflow box here was a yellow alarm over a
    // receipt whose worker never asked for anything.
    if (consequence) return null;
    return <MissingWorkflowNotice />;
  }
  return (
    <RequestApprovalButton
      canRequest={canRequest}
      consequence={consequence}
      onClick={onClick}
      isRequesting={isRequesting}
    />
  );
}

/**
 * A request somebody still has to settle: where it sits, who holds it, and
 * the decision buttons. One request state — the open one — kept together so
 * the card's own branching is only about which state that is.
 */
function OpenRequest({
  approval,
  onApprove,
  onReject,
}: {
  approval: ApprovalRequest;
  onApprove?: (approval: ApprovalRequest, notes?: string) => Promise<void>;
  onReject?: (approval: ApprovalRequest, notes: string) => Promise<void>;
}) {
  const { t } = useTranslation("approvals");
  const {
    data: members,
    isError: membersFailed,
    error: membersError,
    refetch: refetchMembers,
  } = useOrgMembers();
  const hasAction = useHasApprovalAction(approval);
  const currentUserId = useAuthStore((state) => state.user?.id);

  const memberNameById = new Map(
    (members ?? []).map((m) => [m.id, m.full_name ?? m.email]),
  );

  const currentStageDef = approval.workflow_stages?.find(
    (s) => s.order === approval.current_stage,
  );

  const currentStageApproverIds = currentStageDef?.approver_user_ids ?? [];
  const currentStageApproverNames = currentStageApproverIds
    .map((uid) => memberNameById.get(uid) ?? null)
    .filter((name): name is string => name !== null);

  const pastDecisions =
    approval.decisions?.filter(
      (d) => d.status === "APPROVED" || d.status === "REJECTED",
    ) ?? [];

  // The requester cannot decide on their own open request unless the org
  // allows self-approval. The server already answers `viewer_can_decide:
  // false` for exactly that case, so the "any approver" hint must not tell
  // them they are one of them.
  const isSelfBlocked =
    approval.created_by === currentUserId &&
    approval.viewer_can_decide === false;

  return (
    <div className="flex flex-col gap-2">
      <ApprovalDeadEndNotice subject={approval} request={approval} />
      {/* Same action label as the queues — the decision reads the same on
          every screen that lets the user act on this request, and the same
          way when it does not. */}
      <p className="mb-1 text-[10px] font-medium uppercase tracking-widest text-on-muted">
        {hasAction
          ? t("dashboard.section.yourAction")
          : t("dashboard.section.awaitingDecision")}
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-on-muted">
        <ApprovalBadge
          status={approval.status}
          stage={{
            current: approval.current_stage,
            total: approval.total_stages,
          }}
        />

        {currentStageDef && (
          <span className="inline-flex items-center gap-1">
            <Clock size={12} />
            {stageName(currentStageDef)}
          </span>
        )}

        {currentStageApproverIds.length > 0 ? (
          <span className="inline-flex items-center gap-1">
            <Users size={12} />
            {t("request.approvers")}:{" "}
            {currentStageApproverNames.length > 0 ? (
              currentStageApproverNames.join(", ")
            ) : membersFailed ? (
              <InlineQueryError
                error={membersError}
                onRetry={() => void refetchMembers()}
                className="text-xs"
              />
            ) : (
              currentStageApproverIds.length
            )}
          </span>
        ) : isSelfBlocked ? (
          <span className="inline-flex items-center gap-1">
            <Users size={12} />
            {t("request.ownRequestCannotApprove")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1">
            <Users size={12} />
            {t("request.anyApprover")}
          </span>
        )}

        {pastDecisions.map((d) => (
          <span key={d.id} className="inline-flex items-center gap-1">
            <CheckCheck size={12} className="text-accent-600" />
            {d.notes?.startsWith(AUTO_PASSED_NOTE_PREFIX)
              ? t("request.autoPassed")
              : t("request.approvedBy", {
                  name: d.approver_name ?? t("request.unknownApprover"),
                })}
          </span>
        ))}
      </div>

      <ApprovalDecisionButtons
        approval={approval}
        onApprove={onApprove}
        onReject={onReject}
      />
    </div>
  );
}

export function ApprovalActions({
  targetType,
  targetId,
  approval,
  requestConsequence,
  onApprove,
  onRequest,
  requestModule,
  onReject,
}: ApprovalActionsProps) {
  const { t } = useTranslation("approvals");

  const requestApproval = useRequestApproval();
  // The backend refuses the request for an account without the write right
  // — of the approvals module for the generic endpoint, of the target
  // module for its proxy. The button says so before the click, not after.
  const canRequest = useCanWrite(requestModule ?? "approvals");

  const [isOverrideRequesting, setIsOverrideRequesting] = useState(false);

  const handleRequestApproval = async () => {
    if (onRequest) {
      setIsOverrideRequesting(true);
      try {
        await onRequest();
        toast.success(t("request.requested"));
      } catch (err) {
        toast.error(extractApiError(err, t("request.requestFailed")));
      } finally {
        setIsOverrideRequesting(false);
      }
      return;
    }
    try {
      await requestApproval.mutateAsync({ targetType, targetId });
      toast.success(t("request.requested"));
    } catch (err) {
      toast.error(extractApiError(err, t("request.requestFailed")));
    }
  };

  const isRequesting = requestApproval.isPending || isOverrideRequesting;
  const requestAffordance = (
    <RequestAffordance
      targetType={targetType}
      canRequest={canRequest}
      consequence={requestConsequence}
      onClick={handleRequestApproval}
      isRequesting={isRequesting}
    />
  );

  if (approval === undefined) {
    // The read that says which request this target has has not landed. "No
    // request" is a claim about the target, and this card used to make it on
    // an empty guess — the button then took an approved document back to the
    // approval queue. Nothing to say until the answer arrives.
    return null;
  }

  if (!approval) {
    return requestAffordance;
  }

  if (approval.status === "APPROVED") {
    return (
      <div className="flex flex-col gap-1">
        <ApprovalBadge status={approval.status} />
        {approval.decisions
          ?.filter((d) => d.status === "APPROVED")
          .map((d) => (
            <p key={d.id} className="text-xs text-on-muted">
              {d.notes?.startsWith(AUTO_PASSED_NOTE_PREFIX)
                ? t("request.autoPassed")
                : (d.approver_name ?? t("request.unknownApprover"))}{" "}
              — {d.decided_at ? formatDate(d.decided_at) : ""}
            </p>
          ))}
      </div>
    );
  }

  if (approval.status === "REJECTED") {
    const rejection = approval.decisions?.find((d) => d.status === "REJECTED");
    return (
      <ResolvedRequest
        status={approval.status}
        note={
          rejection?.approver_name
            ? `${t("request.rejectedBy", { name: rejection.approver_name })}${
                rejection.notes ? `: ${rejection.notes}` : ""
              }`
            : null
        }
        request={requestAffordance}
      />
    );
  }

  if (approval.status === "CANCELLED") {
    // a withdrawn request used to fall through to the default
    // branch, which offered Approve and Reject on a request the API
    // answers with a conflict. The document stays in PENDING_APPROVAL —
    // withdrawing takes back the request, not the document — so the one
    // thing left to do is send it again.
    return (
      <ResolvedRequest
        status={approval.status}
        note={
          approval.cancelled_at
            ? t("request.withdrawnOn", {
                date: formatDate(approval.cancelled_at),
              })
            : null
        }
        request={requestAffordance}
      />
    );
  }

  return (
    <OpenRequest
      approval={approval}
      onApprove={onApprove}
      onReject={onReject}
    />
  );
}
