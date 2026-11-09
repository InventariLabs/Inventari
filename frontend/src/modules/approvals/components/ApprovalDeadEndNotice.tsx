import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useAuthStore } from "@/store/authStore";
import type {
  ApprovalRequest,
  ApprovalWorkflow,
} from "@/modules/approvals/api/approvals";
import { useOrgMembers } from "@/modules/approvals/hooks/useOrgMembers";
import { targetPath } from "@/modules/approvals/targetTypes";

/**
 * Anything the server judged unsolvable — a request waiting where nobody
 * can decide it, or a workflow definition whose stage nobody ever will.
 */
export interface DeadEndSubject {
  solvable?: boolean | null;
  undecidable_reason?: string | null;
}

/** The part of a request the reader's next step depends on. */
type DeadEndRequest = Pick<
  ApprovalRequest,
  "created_by" | "created_by_name" | "workflow_stages" | "current_stage"
>;

type WaitingApprovalRequest = NonNullable<
  ApprovalWorkflow["waiting_requests"]
>[number];

interface ApprovalDeadEndNoticeProps {
  subject: DeadEndSubject;
  /**
   * The request itself, when the notice sits beside one. With it the notice
   * tells this reader what they can do — the requester, an administrator and
   * everybody else have different moves — and never advises one the server
   * refuses. Without it the notice judges a workflow definition.
   */
  request?: DeadEndRequest;
  /** The requests already parked on the workflow the notice is judging. */
  waiting?: WaitingApprovalRequest[];
  /** The heading; the request-side sentence by default. */
  title?: string;
  className?: string;
}

const NAMED = "named_approvers_cannot_decide";
const ONLY_REQUESTER = "only_the_requester_can_decide";

/**
 * Says out loud that nobody could decide this, and what the reader can do.
 *
 * On a request, three ways that happens and the server names which: the
 * stage is open to anyone holding the approve grant and nobody in the
 * organization holds it; the stage names people who cannot see approvals
 * at all; or the stage is open and the grant's only holder is the
 * requester, whom the door refuses a self-decision. A workflow definition
 * is judged without a requester, so it carries the first two. All of them
 * used to read exactly like something waiting its turn — and, on a queue
 * that shows only what the reader can act on, like a queue with nothing in
 * it.
 *
 * The cause is the same for every reader; the way out is not. The workflow
 * cannot be changed or switched off while a request waits on it, so the one
 * move that always works belongs to the requester (withdraw), and the move
 * that cures the cause belongs to an administrator (give the access). The
 * rest are told whom to ask.
 */
export function ApprovalDeadEndNotice(props: ApprovalDeadEndNoticeProps) {
  if (props.subject.solvable !== false) return null;
  return <DeadEnd {...props} />;
}

/**
 * The people a named dead end blames: the requester is not among them.
 *
 * The server already left the requester out of what it reports — the decision
 * door refuses a self-decision — so a stage naming them beside somebody who
 * cannot see approvals must not call them unable to decide, nor advise access
 * they already hold. With the opt-in on, an administrator requester counts and
 * the request is solvable, so no banner reaches here at all.
 */
function blamedApprovers(
  reason: string | null | undefined,
  request: DeadEndRequest | undefined,
  stage: { approver_user_ids?: string[] } | undefined,
): { ids: string[]; requesterIsNamed: boolean } {
  const named = stage?.approver_user_ids ?? [];
  const requesterIsNamed =
    reason === NAMED && !!request && named.includes(request.created_by);
  return {
    ids: requesterIsNamed
      ? named.filter((id) => id !== request?.created_by)
      : named,
    requesterIsNamed,
  };
}

/** Whether the self-approval opt-in is a way out of this wait. */
function offersSelfApproval(
  reason: string | null | undefined,
  requesterIsNamed: boolean,
): boolean {
  return reason === ONLY_REQUESTER || (reason === NAMED && requesterIsNamed);
}

function DeadEnd({
  subject,
  request,
  waiting,
  title,
  className,
}: ApprovalDeadEndNoticeProps) {
  const { t } = useTranslation("approvals");
  const currentUserId = useAuthStore((state) => state.user?.id);
  const isAdmin = useHasPermission("admin:access");
  const {
    data: members,
    isError: membersFailed,
    error: membersError,
    refetch: refetchMembers,
  } = useOrgMembers();

  const reason = subject.undecidable_reason;
  const isRequester = !!request && request.created_by === currentUserId;

  const stage = request?.workflow_stages?.find(
    (s) => s.order === request.current_stage,
  );
  const memberName = new Map(
    (members ?? []).map((m) => [m.id, m.full_name ?? m.email]),
  );
  const { ids: blamedIds, requesterIsNamed } = blamedApprovers(
    reason,
    request,
    stage,
  );
  const names = blamedIds
    .map((id) => memberName.get(id))
    .filter((name): name is string => !!name)
    .join(", ");

  const cause =
    reason === NAMED
      ? names
        ? t("request.deadEndCauseNamed", { names })
        : t("request.deadEndCauseNamedUnknown")
      : reason === ONLY_REQUESTER
        ? t("request.deadEndCauseOnlyRequester")
        : t("request.deadEndCauseNoApprover");

  const steps: ReactNode[] = [];
  const link = (to: string, label: string) => (
    <Link to={to} className="font-medium underline hover:no-underline">
      {label}
    </Link>
  );

  if (request) {
    if (isRequester) steps.push(t("request.deadEndStepWithdraw"));
    if (isAdmin) {
      if (reason === NAMED) {
        steps.push(
          <>
            {names
              ? t("request.deadEndStepGrantNamed", { names })
              : t("request.deadEndStepGrantNamedUnknown")}{" "}
            {link("/settings", t("request.deadEndLinkMembers"))}
          </>,
        );
      } else {
        steps.push(
          <>
            {t("request.deadEndStepGrantApprove")}{" "}
            {link("/settings/roles", t("request.deadEndLinkRoles"))}
          </>,
        );
      }
      if (offersSelfApproval(reason, requesterIsNamed)) {
        steps.push(
          <>
            {t("request.deadEndStepAllowSelf")}{" "}
            {link(
              "/settings/modules/approvals",
              t("request.deadEndLinkSettings"),
            )}
          </>,
        );
      }
      steps.push(t("request.deadEndStepLocked"));
    } else {
      steps.push(
        reason === NAMED
          ? names
            ? t("request.deadEndStepAskAdminNamed", { names })
            : t("request.deadEndStepAskAdminNamedUnknown")
          : t("request.deadEndStepAskAdminApprove"),
      );
    }
    if (!isRequester) {
      steps.push(
        request.created_by_name
          ? t("request.deadEndStepAskRequester", {
              name: request.created_by_name,
            })
          : t("request.deadEndStepAskRequesterUnnamed"),
      );
    }
  } else if (waiting && waiting.length > 0) {
    steps.push(
      <>
        {t("workflows.deadEndWaiting")}{" "}
        {waiting.map((item, index) => {
          const href = targetPath(item.target_type, item.target_id);
          return (
            <span key={item.request_id}>
              {index > 0 && ", "}
              {href ? link(href, item.label) : item.label}
            </span>
          );
        })}
      </>,
      t("workflows.deadEndWaitingHint"),
    );
  } else {
    steps.push(
      reason === NAMED
        ? t("workflows.deadEndFixNamed")
        : t("workflows.deadEndFixOpen"),
    );
  }

  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-2 rounded-md bg-amber-100 px-3 py-2 text-xs text-on-warning",
        className,
      )}
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <div className="flex flex-col gap-1">
        <p className="font-medium">{title ?? t("request.deadEndTitle")}</p>
        <p>{cause}</p>
        {/* Without the members the sentence above names nobody, and "the
            people it names cannot decide" would read as the whole story. */}
        {membersFailed && (
          <InlineQueryError
            error={membersError}
            onRetry={() => void refetchMembers()}
            className="text-xs"
          />
        )}
        <ul className="list-disc space-y-0.5 pl-4">
          {steps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
