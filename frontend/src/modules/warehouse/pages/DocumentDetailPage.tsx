import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { useState, useEffect } from "react";
import { useParams, Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ListChecks } from "lucide-react";
import { toast } from "sonner";
import { todayIso } from "@/utils/formatters";
import { Card } from "@/components/ui/Card";
import { InlineQueryError, QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { TypedSlot } from "@/components/Slot";
import { DocumentHeaderActions } from "@/modules/warehouse/components/ModuleDocumentActions";
import { DocumentDetailExtra } from "@/modules/warehouse/components/DocumentLineExtra";
import { DocumentExecutionSection } from "@/modules/warehouse/components/DocumentExecutionSection";
import { ApprovalRequiredNotice } from "@/modules/warehouse/components/ApprovalRequiredNotice";
import { DocumentApprovalCard } from "@/modules/warehouse/components/DocumentApprovalCard";
import { DocumentDetailLinesCard } from "@/modules/warehouse/components/DocumentDetailLinesCard";
import { DocumentValueTotals } from "@/modules/warehouse/components/DocumentValueTotals";
import { DocumentCorrectionsSection } from "@/modules/warehouse/components/DocumentCorrectionsSection";
import { DocumentExtraCostsSection } from "@/modules/warehouse/components/DocumentExtraCostsSection";
import { DocumentMetadataGrid } from "@/modules/warehouse/components/DocumentMetadataGrid";
import { DocumentExecutionPanel } from "@/modules/warehouse/components/DocumentExecutionPanel";
import { DocumentPackingStep } from "@/modules/warehouse/components/packing/DocumentPackingStep";
import { DocumentShipmentCard } from "@/modules/warehouse/components/shipping/DocumentShipmentCard";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useCanWrite } from "@/hooks/useCanWrite";
import {
  formatDate,
  formatDateTime,
  formatQuantityLocale,
} from "@/utils/formatters";
import { DocumentStatusBadge } from "@/modules/warehouse/components/DocumentStatusBadge";
import {
  executionPanelVisible,
  useApprovalGate,
  workingStatus,
} from "@/modules/warehouse/components/documentApprovalGate";
import { documentConfirmedAt } from "@/modules/warehouse/components/documentConfirmation";
import { DocumentStatusTimeline } from "@/modules/warehouse/components/DocumentStatusTimeline";
import DocumentDetailModals from "@/modules/warehouse/components/DocumentDetailModals";
import { DocumentScanSessionNotice } from "@/modules/warehouse/components/DocumentScanSessionNotice";
import { useDocumentPartnerOptions } from "@/modules/warehouse/hooks/useDocumentPartnerOptions";
import { useDocumentPlaceNames } from "@/modules/warehouse/hooks/useDocumentPlaces";
import {
  cancelReleasesStock,
  mayBePlanned,
  UNDOABLE_DOCUMENT_TYPES,
} from "@/modules/warehouse/types";
import {
  useDocument,
  useDocumentWorkflow,
  useDocumentCorrections,
  useDuplicateDocument,
  useSetLineTarget,
  useUpdateDocument,
} from "@/modules/warehouse/hooks/useDocuments";
import {
  useApproveDocument,
  useDocumentApproval,
  useDocumentApprovalRequirement,
  useRejectDocument,
  useRequestDocumentApproval,
} from "@/modules/warehouse/hooks/useDocumentApproval";
import { DocumentApprovalRejectedBanner } from "@/modules/warehouse/components/DocumentApprovalRejectedBanner";
import { useDocumentActions } from "@/modules/warehouse/hooks/useDocumentActions";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { useDocumentDetailHashOpen } from "@/modules/warehouse/hooks/useDocumentDetailHashOpen";
import type { ConfirmAction } from "@/modules/warehouse/hooks/useDocumentActions";
import { useModules } from "@/contexts/ModulesContext";

/** The request the banner and the approval card below may speak about.
 *
 * A rejection is the document's present only while the document is still
 * the draft the rejection left behind: there the banner's "edit and
 * re-submit" is the next step and the card's "Rejected · Request
 * Approval" is the way back. Reworked and confirmed again — under the
 * threshold, so no approval was needed and none is open — the request is
 * history: the header says CONFIRMED, and restating the rejection beside
 * it gave the reader two statuses at once and an action on a document
 * that no longer waits for one. The history stays in the approvals
 * module, and `null` is the slot's own word for "nothing waits here".
 *
 * `undefined` is passed through unchanged: the read has not landed, and
 * the card keeps saying nothing until it does.
 */
function speakingApproval<TApproval extends { status?: string }>(
  approval: TApproval | null | undefined,
  docStatus: string,
): TApproval | null | undefined {
  if (approval?.status !== "REJECTED") return approval;
  return docStatus === "DRAFT" ? approval : null;
}

/** The three fields the approval slot gets from this page, kept here so the
 * page's render stays a render.
 *
 * `approval` is the read that answers for the card — the type list cannot:
 * the server scopes it by `approvals:read`, so a request raised by somebody
 * else is invisible there and the card would offer "Request Approval" over an
 * open one. `docStatus` is what keeps that answer about the document as it
 * stands: a rejection the document has moved past is history (see
 * `speakingApproval`), and the card is handed none.
 *
 * `requestModule` names this module's own proxy endpoint, which the documents
 * router answers to `warehouse:write`, so the request button is gated on the
 * right the API checks.
 *
 * `requestConsequence` is the sentence the card asks with on a confirmed
 * document, where the request is a state change: the document goes back to
 * the approval queue and stays there.
 */
function approvalSlotData<TApproval extends { status?: string }>(
  approval: TApproval | null | undefined,
  docStatus: string,
  isConfirmed: boolean,
  t: (key: string) => string,
): {
  approval: TApproval | null | undefined;
  requestModule: string;
  requestConsequence: string | undefined;
} {
  return {
    approval: speakingApproval(approval, docStatus),
    requestModule: "warehouse",
    requestConsequence: isConfirmed
      ? t("confirmDialog.requestApprovalMessage")
      : undefined,
  };
}

/** The sentence the confirm dialog asks with, kept here so the page's render
 * stays a render. Each action names the consequence the server's own rules
 * settle, so the message cannot promise an outcome the server overrules.
 *
 * `doc` is structural on purpose — the predicate in `cancelReleasesStock`
 * reads two fields, and this helper reaches no further than it does.
 */
/**
 * The facts the confirm sentence is built from, read once.
 *
 * The profile answers whether an exception to "confirms straight through"
 * exists at all — a threshold somebody configured — and the
 * approval-requirement endpoint answers whether this document waits for an
 * approval and whether anybody can give it one. Without a threshold there is
 * no exception to name, and the sentence used to name one anyway. The module
 * switch is the fourth fact for the same reason: with the approvals module
 * off the server's gate stands down entirely, so there is no queue for any
 * sentence to name.
 */
function confirmFacts(
  requirement:
    | {
        approval_required: boolean;
        workflow_configured: boolean;
        approval_solvable?: boolean;
        undecidable_reason?: string | null;
        undecidable_stage?: string | null;
      }
    | undefined,
  profile: { approval_threshold?: string | number | null } | undefined,
  approvalsEnabled: boolean,
): ConfirmFacts {
  const threshold = profile?.approval_threshold;
  return {
    required: approvalsEnabled && (requirement?.approval_required ?? false),
    workflowConfigured: requirement?.workflow_configured ?? false,
    hasThreshold: threshold != null && String(threshold).trim() !== "",
    approvalsEnabled,
    deadEnd:
      requirement?.approval_solvable === false
        ? {
            reason: requirement.undecidable_reason ?? null,
            stage: requirement.undecidable_stage ?? null,
          }
        : null,
  };
}

/** The confirm dialog's heading. The one-step action names its own, because
 * that sentence is built behind a branch the key checker cannot follow. */
export function confirmDialogTitle(
  confirmAction: ConfirmAction,
  t: (key: string, options?: Record<string, unknown>) => string,
  sendsForApproval = false,
): string {
  if (!confirmAction) return "";
  if (confirmAction === "postNow") {
    // The button said "Send for approval"; the dialog it opens says the same.
    return sendsForApproval
      ? t("confirmDialog.postNowApprovalTitle")
      : t("confirmDialog.postNowTitle");
  }
  if (confirmAction === "undo") {
    return t("confirmDialog.undoTitle");
  }
  return t(`confirmDialog.${confirmAction}Title`);
}

/** The confirm dialog's tone: red where the act destroys or abandons. */
function confirmDialogVariant(
  confirmAction: ConfirmAction,
): "danger" | "default" {
  return confirmAction === "delete" || confirmAction === "cancel"
    ? "danger"
    : "default";
}

/** What the confirm sentence is built from; see `confirmFacts`. */
interface ConfirmFacts {
  required: boolean;
  workflowConfigured: boolean;
  hasThreshold: boolean;
  approvalsEnabled: boolean;
  /**
   * Set when the document would be sent to a stage nobody could decide for
   * the person confirming: the sentence says so before the click instead of
   * promising a queue the request would never reach.
   */
  deadEnd?: { reason: string | null; stage: string | null } | null;
}

export function confirmDialogMessage(
  confirmAction: ConfirmAction,
  doc: { type: string; status: string },
  facts: ConfirmFacts,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  // Cancelling a document that holds a reservation gives the reserved stock
  // back, and that is the part worth saying out loud: it is the reason to
  // reach for this on a document stuck at execution. A receipt never
  // reserves — for it the sentence promised a return that never happened.
  if (confirmAction === "cancel" && cancelReleasesStock(doc.type, doc.status)) {
    return t("confirmDialog.cancelReservedMessage");
  }
  if (confirmAction === "postNow") {
    // The one-step action posts the stock. Where the profile demands an
    // approval, the same press only sends it there — say which one this is
    // before the click, not after it.
    if (facts.required) {
      // Nobody can give the approval yet, so the press is refused outright,
      // exactly as the confirm dialog says; promising the queue here was a
      // promise the server disproved.
      if (!facts.workflowConfigured) {
        return t("confirmDialog.confirmMessageNoWorkflow");
      }
      return t("confirmDialog.postNowApprovalMessage");
    }
    // The rule answers for the type and the value it can weigh; an
    // organization that set a threshold may still be overruled server-side,
    // exactly as the confirm dialog says.
    if (facts.hasThreshold && facts.approvalsEnabled) {
      return t("confirmDialog.postNowMessageConditional");
    }
    return t("confirmDialog.postNowMessage");
  }
  if (confirmAction === "undo") {
    return t("confirmDialog.undoMessage");
  }
  if (confirmAction === "confirm") {
    if (facts.required) {
      // Confirmation is refused outright while the profile demands an
      // approval nobody can give, so promising a place in the queue here
      // was a promise the next click disproved with a 400.
      if (!facts.workflowConfigured) {
        return t("confirmDialog.confirmMessageNoWorkflow");
      }
      // The same verdict the parked request would carry, asked before the
      // request exists: confirming parks the document either way, and the
      // sentence must not call a dead end "the approval queue".
      if (facts.deadEnd) {
        const stage = facts.deadEnd.stage ?? "";
        if (facts.deadEnd.reason === "named_approvers_cannot_decide") {
          return t("confirmDialog.confirmMessageDeadEndNamed", { stage });
        }
        if (facts.deadEnd.reason === "only_the_requester_can_decide") {
          return t("confirmDialog.confirmMessageDeadEndOnlyYou", { stage });
        }
        return t("confirmDialog.confirmMessageDeadEndNoApprover", { stage });
      }
      return t("confirmDialog.confirmMessageApproval");
    }
    // The type is not gated, and the value threshold still is server
    // business — but an organization that has configured no threshold has
    // no exception to name, and the sentence used to name it anyway. Nor
    // has one whose approvals module is off: the gate stands down with it,
    // so nothing is sent anywhere and the threshold is inert.
    if (facts.hasThreshold && facts.approvalsEnabled) {
      return t("confirmDialog.confirmMessageConditional");
    }
    return t("confirmDialog.confirmMessage");
  }
  return confirmAction ? t(`confirmDialog.${confirmAction}Message`) : "";
}

/** Sets the document's partner from the metadata grid and says how it went,
 * kept here so the page's render stays a render. An empty choice clears it. */
function changePartner(
  updateDocument: ReturnType<typeof useUpdateDocument>,
  docId: string,
  partnerId: string,
  t: (key: string) => string,
): void {
  updateDocument.mutate(
    { id: docId, data: { partner_id: partnerId || null } },
    {
      onSuccess: () => toast.success(t("toast.updated")),
      onError: (err) =>
        toast.error(extractApiError(err, t("errors.updateFailed"))),
    },
  );
}

/** Asks for approval from a scanning sheet that could not start, then closes
 * it. `mutate`, not an awaited `mutateAsync`: the start-failure screen's
 * button awaits nothing, so the factory's toast is where a refusal is read. */
function requestApprovalFromSheet(
  requestApproval: ReturnType<typeof useRequestDocumentApproval>,
  docId: string,
  t: (key: string) => string,
  close: () => void,
): void {
  requestApproval.mutate(
    { docId },
    {
      onSuccess: () => {
        toast.success(t("toast.approvalRequested"));
        close();
      },
    },
  );
}

/** Whether Undo can still reverse the whole document in one press.
 *
 * Nothing may have restated the document yet — a correction in flight has
 * already changed what is "left to undo", and the server would refuse the
 * whole-document reversal. A failed read of that list is not "no
 * corrections": the button waits rather than offering an action the server
 * may refuse for a reason the screen could not see. */
function offersUndo(
  doc:
    | { type: string; status: string; reversed_by_id?: string | null }
    | undefined,
  corrections: { status: string }[] | undefined,
  correctionsFailed: boolean,
): boolean {
  if (!doc || doc.status !== "COMPLETED") return false;
  if (!UNDOABLE_DOCUMENT_TYPES.has(doc.type)) return false;
  if (doc.reversed_by_id) return false;
  if (correctionsFailed) return false;
  return !(corrections ?? []).some((c) => c.status !== "CANCELLED");
}

// Line quantities are counted in the interface language: at most three
// decimals, and the mark a reader of that language writes.
function formatQuantity(value: number): string {
  return formatQuantityLocale(String(value), 3);
}

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const { t } = useTranslation("warehouse");
  const [editOpen, setEditOpen] = useState(false);
  const canWrite = useCanWrite("warehouse");
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [returnOpen, setReturnOpen] = useState(false);
  const [pickingOpen, setPickingOpen] = useState(false);
  const [receivingOpen, setReceivingOpen] = useState(false);
  const [notesEditValue, setNotesEditValue] = useState<string | null>(null);

  const updateDocument = useUpdateDocument();

  const {
    data: doc,
    isLoading,
    isError,
    error,
    refetch,
  } = useDocument(id ?? "");
  const approveDocument = useApproveDocument();
  const requestDocumentApproval = useRequestDocumentApproval();
  const rejectDocument = useRejectDocument();
  // Gate the approval fetch on the module being
  // enabled — fetching approval data for an org without the approvals
  // module is wasted round-trips and (worse) creates QueryClient noise
  // that triggers useModules from children components needlessly.
  const { isModuleEnabled } = useModules();
  const { data: approval } = useDocumentApproval(id, {
    enabled: isModuleEnabled("approvals"),
  });
  // The confirm dialog names the consequence the server's own rule settles —
  // the profile's listed types and threshold, and, when the profile names
  // neither, an active approval workflow for documents. The page used to
  // recompute the workflow half itself from the approvals module's list,
  // which was a second definition of one rule.
  const { data: approvalRequirement } = useDocumentApprovalRequirement(id, {
    enabled: isModuleEnabled("approvals"),
  });
  const { data: documentProfile } = useDocumentProfile();
  const status = doc ? workingStatus(doc) : undefined;
  const gate = useApprovalGate(status, approvalRequirement, approval);
  // One read of the three facts the sentence is built from — see
  // `confirmFacts`, kept out of the render so this stays a render.
  const facts = confirmFacts(
    approvalRequirement,
    documentProfile,
    isModuleEnabled("approvals"),
  );
  const { data: corrections, isError: correctionsFailed } =
    useDocumentCorrections(doc?.status === "COMPLETED" ? (id ?? "") : "");
  const { fieldProps: pp } = useDocumentPartnerOptions(doc); // the form's picker
  // The grid names the two places the document stands between; each line's
  // picker searches the shelves on the server (see DocumentFormModal).
  const storages = useDocumentPlaceNames(doc);
  const setLineTarget = useSetLineTarget();
  const {
    confirmDocument,
    completeDocument,
    postDocumentNow,
    cancelDocument,
    deleteDocument,
    undoDocument,
  } = useDocumentWorkflow();
  const duplicateMutation = useDuplicateDocument();

  const {
    confirmAction,
    setConfirmAction,
    handleAction,
    handleApplyCorrection,
    handleComplete,
    handleSessionComplete,
    handleDownloadPdf,
    handleDuplicate,
    isUndoPending,
    door,
    setExecutionOpen,
    isPdfDownloading,
    unitMismatch,
    confirmUnitChoice,
    dismissUnitMismatch,
    receiptExpiry,
  } = useDocumentActions({
    docId: id,
    doc,
    docStatus: status,
    duplicateMutation,
    confirmMutation: confirmDocument,
    postNowMutation: postDocumentNow,
    completeMutation: completeDocument,
    cancelMutation: cancelDocument,
    deleteMutation: deleteDocument,
    undoMutation: undoDocument,
    onOpenCorrection: () => setCorrectionOpen(true),
  });

  const { setHeader } = useModulePageHeader();

  const canUndo = offersUndo(doc, corrections, correctionsFailed);

  useEffect(() => {
    if (!doc) return;
    setHeader({
      backTo: "/warehouse",
      title: documentTitle(t, doc),
      subtitle: doc.is_opening
        ? `${t(`types.${doc.type}`, { defaultValue: doc.type })} · ${t("openingStock.badge")}`
        : t(`types.${doc.type}`, { defaultValue: doc.type }),
      statusBadge: <DocumentStatusBadge status={doc.status} />,
      actions: (
        <DocumentHeaderActions
          doc={doc}
          isApplyCorrectionPending={
            confirmDocument.isPending || completeDocument.isPending
          }
          isCompletePending={completeDocument.isPending}
          isPostNowPending={postDocumentNow.isPending}
          isPlanned={mayBePlanned(doc.type, doc.scheduled_date, todayIso())}
          approvalRequired={facts.required}
          isPdfDownloading={isPdfDownloading}
          // any active (non-terminal) approval request blocks
          // execution — PENDING alone missed IN_PROGRESS requests.
          {...gate}
          onApplyCorrection={handleApplyCorrection}
          onEdit={() => setEditOpen(true)}
          onConfirm={() => setConfirmAction("confirm")}
          onPostNow={() => setConfirmAction("postNow")}
          onCancel={() => setConfirmAction("cancel")}
          onDelete={() => setConfirmAction("delete")}
          onExecute={door.execute}
          onReturn={() => setReturnOpen(true)}
          onUndo={() => setConfirmAction("undo")}
          canUndo={canUndo}
          isUndoPending={isUndoPending}
          onDownloadPdf={handleDownloadPdf}
          onStartPicking={() => setPickingOpen(true)}
          onStartReceiving={() => setReceivingOpen(true)}
          onDuplicate={handleDuplicate}
          isDuplicatePending={duplicateMutation.isPending}
          t={t}
        />
      ),
    });
  }, [
    doc,
    t,
    setHeader,
    isPdfDownloading,
    confirmDocument.isPending,
    completeDocument.isPending,
    postDocumentNow.isPending,
    duplicateMutation.isPending,
    facts.required,
    canUndo,
    isUndoPending,
    handleApplyCorrection,
    handleDownloadPdf,
    handleDuplicate,
    setConfirmAction,
    door.execute,
    gate,
  ]);

  // Open the page's modals from the URL hash (the rejected banner's #edit
  // CTA, a scanned printout's #receive/#pick/#execute) — the effects and
  // their reasons live in the hook, the page stays a render.
  useDocumentDetailHashOpen(
    location.hash,
    doc,
    setEditOpen,
    setReceivingOpen,
    setPickingOpen,
    setExecutionOpen,
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
      </div>
    );
  }

  if (isError && !isNotFoundError(error)) {
    // A network failure is not a deleted document.
    return (
      <QueryError
        message={t("errors.loadDocumentFailed")}
        onRetry={() => void refetch()}
      />
    );
  }

  if (!doc) {
    return (
      <RecordNotFound
        title={t("detail.notFound")}
        backTo="/warehouse"
        backLabel={t("detail.backToList")}
      />
    );
  }

  const isDraft = doc.status === "DRAFT";
  const isConfirmed = status === "CONFIRMED";
  const isCorrection = doc.type === "CORRECTION";
  // Approval actions are only meaningful for documents that can still be
  // approved: COMPLETED/CANCELLED are terminal, and the approval history
  // for those remains visible in the approvals module.
  const showApprovalSlot =
    !isDraft && doc.status !== "COMPLETED" && doc.status !== "CANCELLED";

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="warehouse" />
      {approval && approval.status === "REJECTED" && (
        <DocumentApprovalRejectedBanner
          approval={speakingApproval(approval, doc.status)}
          documentId={id ?? ""}
        />
      )}

      {showApprovalSlot && isModuleEnabled("approvals") && (
        <DocumentApprovalCard>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <TypedSlot
              name="approval_status_badge"
              data={{
                targetType: "document",
                targetId: doc.id,
                ...approvalSlotData(approval, doc.status, isConfirmed, t),
                onApprove: async (_requestId, notes) => {
                  await approveDocument.mutateAsync({ docId: doc.id, notes });
                },
                onRequest: async () => {
                  await requestDocumentApproval.mutateAsync({ docId: doc.id });
                },
                onReject: async (_requestId, notes) => {
                  await rejectDocument.mutateAsync({ docId: doc.id, notes });
                },
              }}
            />
            {doc.status === "PENDING_APPROVAL" && (
              <Link
                to="/approvals"
                className="inline-flex min-h-6 items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700 hover:underline md:min-h-0"
              >
                <ListChecks size={14} />
                {t("approvalQueueLink")}
              </Link>
            )}
          </div>
        </DocumentApprovalCard>
      )}
      <ApprovalRequiredNotice gate={gate} />

      {/* The session is open over the document: say so where the reader
          lands, with the two ways out — the same two the scanning sheet
          offers once it is open. A session that finished over a document
          nobody completed gets the completion its summary would have made.
          The query and the kind's branching stay in the notice, so this
          stays a render. */}
      <DocumentScanSessionNotice
        document={doc}
        onResumeReceiving={() => setReceivingOpen(true)}
        onResumePicking={() => setPickingOpen(true)}
        onComplete={handleSessionComplete}
        isCompletePending={completeDocument.isPending}
      />

      {pp.partnersError != null && (
        <InlineQueryError error={pp.partnersError} onRetry={pp.retryPartners} />
      )}

      <Card className="p-4 sm:p-6 space-y-5">
        <DocumentMetadataGrid
          doc={doc}
          isDraft={isDraft}
          {...pp}
          storages={storages}
          notesEditValue={notesEditValue}
          onNotesChange={setNotesEditValue}
          onNotesBlur={() => {
            if (notesEditValue === null) return;
            const trimmed = notesEditValue.trim();
            if (trimmed === (doc.notes ?? "")) {
              setNotesEditValue(null);
              return;
            }
            updateDocument.mutate(
              { id: doc.id, data: { notes: trimmed || null } },
              {
                onSuccess: () => {
                  setNotesEditValue(null);
                  toast.success(t("toast.updated"));
                },
                onError: (err) =>
                  toast.error(extractApiError(err, t("errors.updateFailed"))),
              },
            );
          }}
          onPartnerChange={(partnerId) =>
            changePartner(updateDocument, doc.id, partnerId, t)
          }
          formatDate={formatDate}
          formatDateTime={formatDateTime}
          t={t}
        />

        <DocumentStatusTimeline
          status={doc.status}
          createdAt={doc.created_at}
          confirmedAt={documentConfirmedAt(doc)}
          completedAt={doc.completed_at}
          cancelledAt={doc.cancelled_at ?? null}
          approval={doc.approval}
          formatDate={formatDateTime}
          isCorrection={isCorrection}
        />
      </Card>

      {executionPanelVisible(isConfirmed, door.panelOpen, gate, doc.type) && (
        <DocumentExecutionPanel
          document={doc}
          isPending={completeDocument.isPending}
          onCancel={() => setExecutionOpen(false)}
          onSubmit={handleComplete}
        />
      )}

      <DocumentExecutionSection document={doc} isCorrection={isCorrection} />

      <DocumentShipmentCard shipment={doc.shipment} />

      <DocumentPackingStep
        document={doc}
        onComplete={handleSessionComplete}
        isCompletePending={completeDocument.isPending}
      />

      <DocumentDetailLinesCard
        document={doc}
        formatQuantity={formatQuantity}
        targetChangePending={setLineTarget.isPending}
        onLineTargetChange={(lineId, target) =>
          setLineTarget.mutate({
            docId: doc.id,
            lineId,
            targetLocationId: target,
          })
        }
      />

      <DocumentValueTotals document={doc} />

      {/* Freight, duty and insurance belong in the value of the goods they
          arrived with, and only a receipt can carry them. */}
      {doc.type === "IN" && <DocumentExtraCostsSection documentId={doc.id} />}

      {/* What the document actually did to stock, if anything can have
          happened yet. The lines above say how much was expected and how
          much was done; only the ledger says where it went and out of
          which batch. */}
      <DocumentDetailExtra document={doc} />

      {doc.status === "COMPLETED" &&
        doc.type !== "CORRECTION" &&
        corrections !== undefined && (
          <DocumentCorrectionsSection
            corrections={corrections}
            documentType={doc.type}
            onNewCorrection={() => setCorrectionOpen(true)}
            correctionsTitle={t("corrections.sectionTitle")}
            correctionsNewText={t("corrections.new")}
            correctionsNoneText={t("corrections.none")}
            formatReason={(code) =>
              makeTDynamic(t)(`reasons.correction.codes.${code}`)
            }
            canWrite={canWrite}
            formatDate={formatDateTime}
          />
        )}

      <DocumentDetailModals
        doc={doc}
        editOpen={editOpen}
        onEditClose={() => setEditOpen(false)}
        correctionOpen={correctionOpen}
        onCorrectionClose={() => setCorrectionOpen(false)}
        returnOpen={returnOpen}
        onReturnClose={() => setReturnOpen(false)}
        pickingOpen={pickingOpen}
        onPickingClose={(completed, shipment) => {
          setPickingOpen(false);
          if (completed) handleSessionComplete(shipment);
        }}
        onPickingRequestApproval={() =>
          requestApprovalFromSheet(requestDocumentApproval, doc.id, t, () =>
            setPickingOpen(false),
          )
        }
        receivingOpen={receivingOpen}
        // Leaving the summary completes the document, which books the stock
        // moves — the same step picking ends on.
        onReceivingClose={(completed) => {
          setReceivingOpen(false);
          if (completed) handleSessionComplete();
        }}
        onReceivingRequestApproval={() =>
          requestApprovalFromSheet(requestDocumentApproval, doc.id, t, () =>
            setReceivingOpen(false),
          )
        }
        confirmAction={confirmAction}
        confirmTitle={confirmDialogTitle(confirmAction, t, facts.required)}
        postNowSendsForApproval={facts.required}
        confirmMessage={confirmDialogMessage(confirmAction, doc, facts, t)}
        confirmVariant={confirmDialogVariant(confirmAction)}
        onConfirmAction={handleAction}
        onConfirmCancel={() => setConfirmAction(null)}
        unitMismatch={unitMismatch}
        onUnitMismatchConfirm={confirmUnitChoice}
        onUnitMismatchClose={dismissUnitMismatch}
        receiptExpiry={receiptExpiry}
      />
    </div>
  );
}
