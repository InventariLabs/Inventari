import {
  Pencil,
  Check,
  XCircle,
  Trash2,
  CornerDownLeft,
  Download,
  PackageSearch,
  Copy,
  ArrowDownToLine,
  CalendarClock,
  Send,
  PackageCheck,
  Undo2,
} from "lucide-react";
import {
  executionBlocked,
  executionHintKey,
} from "@/modules/warehouse/components/documentApprovalGate";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import {
  UNDOABLE_DOCUMENT_TYPES,
  undoLabelKey,
} from "@/modules/warehouse/types";

// Both paths end in the same stock movement, so the names have to carry
// what differs: the inline panel takes the document type's verb, the WMS
// session is prefixed "Scan" (see the labels in i18n). A scrap is executed by
// writing the goods off; nothing is picked for anybody.
function executeLabelKeyFor(docType: string) {
  if (docType === "IN" || docType === "INTERNAL_IN")
    return "warehouse:actions.executeReceive";
  if (docType === "SCRAP") return "warehouse:actions.executeScrap";
  return "warehouse:actions.executePick";
}

/**
 * The one-step verb for a draft: what the action does to the stock, in the
 * warehouse's own words. A type with no verb of its own posts under the
 * neutral label rather than borrowing another type's.
 */
function postNowLabelKeyFor(docType: string) {
  switch (docType) {
    case "IN":
    case "INTERNAL_IN":
      return "warehouse:actions.postNowReceive";
    case "OUT":
      return "warehouse:actions.postNowIssue";
    case "INT":
      return "warehouse:actions.postNowMove";
    case "INTERNAL_OUT":
      return "warehouse:actions.postNowConsume";
    case "SCRAP":
      return "warehouse:actions.postNowScrap";
    case "ADJUSTMENT":
      return "warehouse:actions.postNowAdjust";
    default:
      return "warehouse:actions.postNowDefault";
  }
}

// The types the API returns (`is_return_eligible`): a receipt goes back to
// the supplier as a delivery, a delivery comes back as a receipt.
const RETURNABLE_TYPES = new Set(["IN", "OUT", "INT"]);

interface DraftActionsProps {
  isCorrection: boolean;
  canManage: boolean;
  docType: string;
  isPlanned: boolean;
  approvalRequired: boolean;
  isPostNowPending: boolean;
  isCompletePending: boolean;
  isApplyCorrectionPending: boolean;
  onApplyCorrection: () => void;
  onEdit: () => void;
  onPostNow: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onDelete: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

/**
 * What a draft offers. The one-step verb is the primary action; the old
 * confirm step survives as "Plan" in the row's menu for a future-dated
 * document, where a plan is the point, and for goods to be picked first.
 */
function DraftActions({
  isCorrection,
  canManage,
  docType,
  isPlanned,
  approvalRequired,
  isPostNowPending,
  isCompletePending,
  isApplyCorrectionPending,
  onApplyCorrection,
  onEdit,
  onPostNow,
  onConfirm,
  onCancel,
  onDelete,
  t,
}: DraftActionsProps) {
  if (isCorrection) {
    return (
      <>
        <Button
          size="sm"
          leftIcon={<Check size={15} />}
          onClick={onApplyCorrection}
          disabled={isApplyCorrectionPending || isCompletePending}
        >
          {t("warehouse:actions.applyCorrection")}
        </Button>
        {canManage && (
          <Button
            variant="ghostDanger"
            size="sm"
            leftIcon={<Trash2 size={15} />}
            onClick={onDelete}
          >
            {t("warehouse:actions.delete")}
          </Button>
        )}
      </>
    );
  }
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<Pencil size={15} />}
        onClick={onEdit}
      >
        {t("warehouse:actions.edit")}
      </Button>
      <Button
        size="sm"
        leftIcon={
          approvalRequired ? <Send size={15} /> : <PackageCheck size={15} />
        }
        onClick={onPostNow}
        disabled={isPostNowPending || isCompletePending}
      >
        {approvalRequired
          ? t("warehouse:actions.sendForApproval")
          : t(postNowLabelKeyFor(docType))}
      </Button>
      {isPlanned && (
        <ActionMenu
          label={t("warehouse:actions.moreActions")}
          actions={[
            {
              id: "plan",
              label: t("warehouse:actions.plan"),
              icon: <CalendarClock size={15} />,
              onSelect: onConfirm,
            },
          ]}
        />
      )}
      {canManage && (
        <Button
          variant="outline"
          size="sm"
          leftIcon={<XCircle size={15} />}
          onClick={onCancel}
        >
          {t("warehouse:actions.cancelDocument")}
        </Button>
      )}
      {canManage && (
        <Button
          variant="ghostDanger"
          size="sm"
          leftIcon={<Trash2 size={15} />}
          onClick={onDelete}
        >
          {t("warehouse:actions.delete")}
        </Button>
      )}
    </>
  );
}

/** Whether the row offers Undo: a posted receipt, issue or move, when the
 * page says the stock is still there to take back. The type check is the
 * backend's own list — a correction or a stock take is corrected, not undone. */
function offersUndo(
  docType: string,
  docStatus: string,
  canUndo: boolean | undefined,
  onUndo: (() => void) | undefined,
): boolean {
  return (
    docStatus === "COMPLETED" &&
    !!canUndo &&
    UNDOABLE_DOCUMENT_TYPES.has(docType) &&
    !!onUndo
  );
}

/** Whether the row offers a return: a document the server takes one of, and
 * not one Undo has already put back in full, which has nothing left to send. */
function offersReturn(
  docType: string,
  isReversed: boolean | undefined,
): boolean {
  return RETURNABLE_TYPES.has(docType) && !isReversed;
}

/** Cancelling is what releases a confirmed document's hold, so it stays
 * offered on a confirmed or parked document to whoever manages documents. */
function cancelOffersItself(
  isCorrection: boolean,
  isConfirmed: boolean,
  docStatus: string,
): boolean {
  return !isCorrection && (isConfirmed || docStatus === "PENDING_APPROVAL");
}

interface DocumentActionButtonsProps {
  isDraft: boolean;
  isConfirmed: boolean;
  docStatus: string;
  docType: string;
  isApplyCorrectionPending: boolean;
  isCompletePending: boolean;
  isPostNowPending?: boolean;
  isPdfDownloading: boolean;
  canStartPicking: boolean;
  canStartReceiving: boolean;
  isDuplicatePending?: boolean;
  /** The draft may be planned instead of posted now: see `mayBePlanned`. */
  isPlanned?: boolean;
  /** The profile requires an approval for this document: the one-step
   * action sends it there instead of posting it. */
  approvalRequired?: boolean;
  /** True when an approval request is PENDING — execution actions are
   * disabled until the request is resolved (the backend blocks
   * completion/picking anyway; this prevents a dead-end form). */
  hasPendingApproval?: boolean;
  /** Approval is required, none is open or granted: only requesting it is accepted. */
  approvalRequiredNoRequest?: boolean;
  /** ...and no approval workflow is active, so a request cannot be raised either. */
  approvalWorkflowMissing?: boolean;
  /** A posted receipt, issue or move whose stock is still there to take
   * back: the page offers Undo beside Return. */
  canUndo?: boolean;
  /** Undo has already put everything back: a return would have nothing left
   * to send, so none is offered. */
  isReversed?: boolean;
  isUndoPending?: boolean;
  onApplyCorrection: () => void;
  onEdit: () => void;
  onConfirm: () => void;
  onPostNow: () => void;
  onCancel: () => void;
  onDelete: () => void;
  onExecute: () => void;
  onReturn: () => void;
  onUndo?: () => void;
  onDownloadPdf: () => void;
  onStartPicking?: () => void;
  onStartReceiving?: () => void;
  onDuplicate?: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function DocumentActionButtons({
  isDraft,
  isConfirmed,
  docStatus,
  docType,
  isApplyCorrectionPending,
  isCompletePending,
  isPostNowPending = false,
  isPdfDownloading,
  canStartPicking,
  canStartReceiving,
  isDuplicatePending = false,
  isPlanned = false,
  approvalRequired = false,
  hasPendingApproval = false,
  approvalRequiredNoRequest,
  approvalWorkflowMissing,
  canUndo,
  isReversed,
  isUndoPending,
  onApplyCorrection,
  onEdit,
  onConfirm,
  onPostNow,
  onCancel,
  onDelete,
  onExecute,
  onReturn,
  onUndo,
  onDownloadPdf,
  onStartPicking,
  onStartReceiving,
  onDuplicate,
  t,
}: DocumentActionButtonsProps) {
  const isCorrection = docType === "CORRECTION";
  const isCompleted = docStatus === "COMPLETED";
  // Execution the server would refuse says why instead of failing at the
  // last click.
  const gate = {
    hasPendingApproval,
    approvalRequiredNoRequest: !!approvalRequiredNoRequest,
    approvalWorkflowMissing: !!approvalWorkflowMissing,
  };
  const blocked = executionBlocked(gate);
  const hintKey = executionHintKey(gate);
  const executionHint = hintKey ? t(hintKey) : undefined;
  const executeLabelKey = executeLabelKeyFor(docType);
  const canReturn = offersReturn(docType, isReversed);
  // a correction whose first completion failed stays CONFIRMED —
  // keep the apply button available so the user can retry completion.
  const showCorrectionApply =
    isCorrection && (isDraft || docStatus === "CONFIRMED");
  const canWrite = useCanWrite("warehouse");
  // Cancel and delete: the backend checks warehouse:manage, and a test there
  // says so in as many words. This asked for the role names instead, so a
  // custom role holding the key was refused by the screen and accepted by the
  // API — the two have to name the same right (AGENTS.md "gate on a
  // permission, never on a role name").
  const canManage = useCanManage("warehouse");
  // Cancelling a document that has already been confirmed is what releases
  // the stock it reserved, and the API does it for anyone holding
  // warehouse:manage. The screen offered it on a draft only, so a document
  // stuck at execution went on holding a whole shelf with no way out of it
  // for any role — the warehouse's only move was to dispatch what it could
  // and file the rest as a shortage of goods that never left.
  const canCancelInPlace = cancelOffersItself(
    isCorrection,
    isConfirmed,
    docStatus,
  );

  return (
    <div className="flex gap-2 flex-wrap">
      {canWrite && showCorrectionApply && !isDraft && (
        <>
          <Button
            size="sm"
            leftIcon={<Check size={15} />}
            onClick={onApplyCorrection}
            disabled={isApplyCorrectionPending || isCompletePending}
          >
            {t("warehouse:actions.applyCorrection")}
          </Button>
          {/* a stuck CONFIRMED correction (item removed from the
              catalog) can be cancelled — the backend allows cancelling
              CONFIRMED documents, so expose the escape hatch in the UI. */}
          {canManage && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<XCircle size={15} />}
              onClick={onCancel}
            >
              {t("warehouse:actions.cancel")}
            </Button>
          )}
        </>
      )}
      {canWrite && isDraft && (
        <DraftActions
          isCorrection={isCorrection}
          canManage={canManage}
          docType={docType}
          isPlanned={isPlanned}
          approvalRequired={approvalRequired}
          isPostNowPending={isPostNowPending}
          isCompletePending={isCompletePending}
          isApplyCorrectionPending={isApplyCorrectionPending}
          onApplyCorrection={onApplyCorrection}
          onEdit={onEdit}
          onPostNow={onPostNow}
          onConfirm={onConfirm}
          onCancel={onCancel}
          onDelete={onDelete}
          t={t}
        />
      )}
      {canWrite && isConfirmed && docType !== "CORRECTION" && (
        <>
          {canStartReceiving && onStartReceiving && (
            <span title={executionHint}>
              <Button
                variant="outline"
                size="sm"
                leftIcon={<ArrowDownToLine size={15} />}
                onClick={onStartReceiving}
                disabled={blocked}
              >
                {t("warehouse:receiving.start_receiving")}
              </Button>
            </span>
          )}
          {canStartPicking && onStartPicking && (
            <span title={executionHint}>
              <Button
                variant="outline"
                size="sm"
                leftIcon={<PackageSearch size={15} />}
                onClick={onStartPicking}
                disabled={blocked}
              >
                {t("warehouse:picking.start_picking")}
              </Button>
            </span>
          )}
          <span title={executionHint}>
            <Button
              size="sm"
              leftIcon={<Check size={15} />}
              onClick={onExecute}
              disabled={blocked}
            >
              {t(executeLabelKey)}
            </Button>
          </span>
        </>
      )}
      {canCancelInPlace &&
        (canManage ? (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<XCircle size={15} />}
            onClick={onCancel}
          >
            {t("warehouse:actions.cancelDocument")}
          </Button>
        ) : (
          canWrite && (
            // Not a right this role holds, and saying so beats saying
            // nothing: the person reading this is the one holding the
            // stuck document.
            <span title={t("warehouse:actions.cancelNeedsManager")}>
              <Button
                variant="outline"
                size="sm"
                leftIcon={<XCircle size={15} />}
                disabled
              >
                {t("warehouse:actions.cancelDocument")}
              </Button>
            </span>
          )
        ))}
      {canWrite && offersUndo(docType, docStatus, canUndo, onUndo) && (
        <Button
          variant="outline"
          size="sm"
          leftIcon={<Undo2 size={15} />}
          onClick={onUndo}
          disabled={isUndoPending}
        >
          {t(undoLabelKey(docType))}
        </Button>
      )}
      {canWrite && isCompleted && canReturn && (
        <Button
          variant="outline"
          size="sm"
          leftIcon={<CornerDownLeft size={15} />}
          onClick={onReturn}
        >
          {t("warehouse:returns.new")}
        </Button>
      )}
      {(isConfirmed || isCompleted) && (
        <Button
          variant="outline"
          size="sm"
          leftIcon={<Download size={15} />}
          onClick={onDownloadPdf}
          disabled={isPdfDownloading}
        >
          {isPdfDownloading
            ? t("warehouse:actions.generatingPdf")
            : t("warehouse:actions.downloadPdf")}
        </Button>
      )}
      {canWrite && onDuplicate && !isCorrection && (
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<Copy size={15} />}
          onClick={onDuplicate}
          disabled={isDuplicatePending}
        >
          {t("warehouse:actions.duplicate")}
        </Button>
      )}
    </div>
  );
}
