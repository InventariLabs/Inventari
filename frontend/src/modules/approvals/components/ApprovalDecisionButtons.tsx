import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCheck, XCircle, Ban } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { extractApiError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";
import { ApproveConfirmDialog } from "./ApproveConfirmDialog";
import {
  useApproveStage,
  useCancelRequest,
  useRejectRequest,
} from "@/modules/approvals/hooks/useApprovalRequests";
import {
  canWithdrawApproval,
  useCanDecideOnApproval,
} from "@/modules/approvals/hooks/useApprovalPermissions";

/** Statuses no decision can be taken on any more. */
export const TERMINAL_STATUSES = new Set(["APPROVED", "REJECTED", "CANCELLED"]);

interface ApprovalDecisionButtonsProps {
  approval: ApprovalRequest;
  /**
   * Override the default approve mutation. When provided, the button
   * calls this adapter instead of the generic
   * ``/approvals/requests/{id}/approve`` endpoint. Used by the
   * Documents inline-approve page to route through the atomic
   * ``/approvals/documents/{id}/approve`` endpoint that also transitions the
   * document to CONFIRMED.
   */
  onApprove?: (approval: ApprovalRequest, notes?: string) => Promise<void>;
  /**
   * Override the default reject mutation. When provided, the button
   * calls this adapter instead of the generic
   * ``/approvals/requests/{id}/reject`` endpoint. Used by the
   * Documents inline-reject page to route through
   * ``/approvals/documents/{id}/reject`` which also returns the document to
   * DRAFT (rework loop) and notifies the requester — without this
   * adapter, the inline reject would leave the document stuck in
   * PENDING_APPROVAL with a REJECTED request, exactly the dead-end
   * this adapter was meant to fix.
   */
  onReject?: (approval: ApprovalRequest, notes: string) => Promise<void>;
  fullWidth?: boolean;
}

export function ApprovalDecisionButtons({
  approval,
  onApprove,
  onReject,
  fullWidth,
}: ApprovalDecisionButtonsProps) {
  const { t } = useTranslation("approvals");
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [rejectNotes, setRejectNotes] = useState("");
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [showApproveConfirm, setShowApproveConfirm] = useState(false);
  const [isOverrideApproving, setIsOverrideApproving] = useState(false);
  const [isOverrideRejecting, setIsOverrideRejecting] = useState(false);
  const [showReasonError, setShowReasonError] = useState(false);

  const approveStage = useApproveStage();
  const rejectRequest = useRejectRequest();
  const cancelRequest = useCancelRequest();

  const canDecide = useCanDecideOnApproval(approval);
  const canCancel = canWithdrawApproval(approval, currentUserId);

  const handleApprove = async (notes?: string) => {
    setShowApproveConfirm(false);
    try {
      if (onApprove) {
        setIsOverrideApproving(true);
        await onApprove(approval, notes);
      } else {
        await approveStage.mutateAsync({ id: approval.id, notes });
      }
      toast.success(t("request.approvedMessage"));
    } catch (err) {
      toast.error(extractApiError(err, t("request.approveFailed")));
    } finally {
      setIsOverrideApproving(false);
    }
  };

  const handleReject = async () => {
    // The reason is required on the UI side.
    // The backend stays optional (Odoo/Coupa require it on the form,
    // not on the API), so this guard is local to the button.
    if (!rejectNotes.trim()) {
      setShowReasonError(true);
      return;
    }
    try {
      if (onReject) {
        setIsOverrideRejecting(true);
        await onReject(approval, rejectNotes.trim());
      } else {
        await rejectRequest.mutateAsync({
          id: approval.id,
          notes: rejectNotes.trim(),
        });
      }
      toast.success(t("request.rejectedMessage"));
      setShowRejectInput(false);
      setRejectNotes("");
      setShowReasonError(false);
    } catch (err) {
      toast.error(extractApiError(err, t("request.rejectFailed")));
    } finally {
      setIsOverrideRejecting(false);
    }
  };

  // "Withdraw", not "Cancel": the requester takes back their own open
  // request. The dialog used to offer "Cancel request" next to "Cancel" —
  // one cancelled the request, the other cancelled the cancelling.
  const handleWithdraw = async () => {
    try {
      await cancelRequest.mutateAsync({ id: approval.id });
      toast.success(t("request.withdrawnMessage"));
    } catch (err) {
      toast.error(extractApiError(err, t("request.withdrawFailed")));
    }
  };

  // full width is a phone answer, not a layout. Below `sm` the three
  // actions do not fit one row inside a card — the last label broke across
  // two lines and ran past the card edge — so they stack, each filling the
  // width. From `sm` up they sit in one row at the end of the card, each as
  // wide as its label, and the block stops reading as three equal options.
  const widthClass = fullWidth ? "w-full sm:w-auto" : "";
  // The row is what aligns to the end; a button keeps its label centred,
  // which is the whole point of the full-width phone layout.
  const actionClass = cn(widthClass, "whitespace-nowrap");

  // A resolved request has nothing to decide. The check used to live in
  // ApprovalDecisionPanel only, so the detail page — which renders these
  // buttons directly — offered Approve on a rejected or withdrawn
  // request.
  const isTerminal = TERMINAL_STATUSES.has(approval.status);

  // Nothing on offer — render nothing rather than an empty action row. The
  // screens around this one ask the same question to label their heading.
  if (isTerminal || (!canDecide && !canCancel)) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canDecide && (
          <Button
            size="sm"
            variant="primary"
            leftIcon={<CheckCheck size={16} />}
            onClick={() => setShowApproveConfirm(true)}
            isLoading={approveStage.isPending || isOverrideApproving}
            className={actionClass}
          >
            {t("request.approve")}
          </Button>
        )}
        {canDecide && !showRejectInput && (
          <Button
            size="sm"
            variant="ghostDanger"
            leftIcon={<XCircle size={16} />}
            onClick={() => setShowRejectInput(true)}
            className={actionClass}
          >
            {t("request.reject")}
          </Button>
        )}
        {!showRejectInput && canCancel && (
          <>
            {canDecide && (
              /* The divider takes the orientation of the row it separates
a hairline across a stack, a rule beside a row.
                 In fullWidth every button is w-full, so the row wraps into
                 a stack and a vertical rule became a zero-width element on
                 a line of its own — the gap this card showed. */
              <span
                aria-hidden="true"
                className={cn(
                  "bg-border shrink-0",
                  fullWidth
                    ? "my-1 h-px w-full sm:my-0 sm:mx-1 sm:h-5 sm:w-px"
                    : "mx-1 h-5 w-px",
                )}
              />
            )}
            <Button
              size="sm"
              variant="ghost"
              leftIcon={<Ban size={16} />}
              onClick={handleWithdraw}
              disabled={cancelRequest.isPending}
              className={actionClass}
            >
              {t("request.withdrawRequest")}
            </Button>
          </>
        )}
      </div>
      {showRejectInput && (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center justify-end gap-2">
            {/* The field used to carry aria-invalid and nothing
                else — no visible change, no message tied to it. `error`
                gives all three at once (red border, role="alert" message,
                aria-describedby), the same way every other form reports. */}
            <Input
              aria-label={t("request.rejectionReason")}
              placeholder={t("request.rejectionReason")}
              value={rejectNotes}
              onChange={(e) => {
                setRejectNotes(e.target.value);
                if (showReasonError) setShowReasonError(false);
              }}
              error={
                showReasonError
                  ? t("request.rejectionReasonRequired")
                  : undefined
              }
              wrapperClassName="w-auto min-w-0 flex-1 basis-56"
            />
            {/* ui-pattern: filled-destructive — this row is the confirmation
                step itself rather than a dialog, so rejecting is what the row
                exists for and the reason field beside it says so */}
            <Button
              size="sm"
              variant="danger"
              onClick={handleReject}
              isLoading={rejectRequest.isPending || isOverrideRejecting}
            >
              {t("request.confirmReject")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setShowRejectInput(false);
                setRejectNotes("");
                setShowReasonError(false);
              }}
            >
              {t("request.cancel")}
            </Button>
          </div>
        </div>
      )}

      {/* the friction goes where the consequence is. Approving is
          final — it records the decision and, for a document, confirms it
          for warehouse execution (the stock moves later, at the receipt) —
 so it asks, exactly as the bulk action has since.
          Withdrawing your own open request changes nothing about the
          document and no longer opens a dialog for it. */}
      <ApproveConfirmDialog
        open={showApproveConfirm}
        approval={approval}
        onConfirm={handleApprove}
        onCancel={() => setShowApproveConfirm(false)}
      />
    </div>
  );
}
