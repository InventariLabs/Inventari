import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, ScanLine, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { cn } from "@/lib/utils";
import { documentsReceivingApi } from "@/modules/warehouse/api/documents_receiving";
import { documentsPickingApi } from "@/modules/warehouse/api/documents_picking";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { isPackedType } from "@/modules/warehouse/components/packing/DocumentPackingStep";
import {
  useDocumentScanSession,
  type ScanSessionKind,
} from "@/modules/warehouse/hooks/useDocumentScanSession";

interface DocumentScanSessionNoticeProps {
  /**
   * The document, for four of its facts. Its status: only CONFIRMED and
   * PENDING_APPROVAL can stand a session over them — a session opens on
   * CONFIRMED, and raising an approval request moves that document to the
   * queue without closing the session it was running — so the rest of the
   * states are not asked at all. Its type: a dispatch completes in its
   * Packing step. Its confirmation: a session older than that ran over an
   * earlier version of the document.
   */
  document: Pick<WarehouseDocument, "id" | "status" | "type" | "confirmed_at">;
  /** Opens the receiving sheet; which sheet is the kind's business, not the
   * reader's. */
  onResumeReceiving: () => void;
  onResumePicking: () => void;
  /** Completes the document, which books what a finished session counted. */
  onComplete: () => void;
  isCompletePending: boolean;
  className?: string;
}

/**
 * Says on the document how far an unfinished scanning session got.
 *
 * Closing the sheet pauses the session, so it no longer blocks anything:
 * the notice reports the progress and offers to continue it — whoever
 * presses it takes the session over — or to complete the document with what
 * was scanned. Discarding the scans stays a secondary way out, asked
 * for twice because it cannot be undone.
 *
 * A session that finished over a document nobody completed — its summary
 * left by the back arrow or a closed tab — gets its own sentence: every line
 * reads done and nothing is booked, which the page did not say anywhere.
 *
 * The read lives here so the page stays a render: it hands over the
 * document, the state it is in and the doors, and gets nothing back to
 * branch on.
 */
export function DocumentScanSessionNotice({
  document,
  onResumeReceiving,
  onResumePicking,
  onComplete,
  isCompletePending,
  className,
}: DocumentScanSessionNoticeProps) {
  const { t } = useTranslation("warehouse");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { id: documentId, status: documentStatus } = document;
  const { data: session } = useDocumentScanSession(documentId, {
    enabled:
      documentStatus === "CONFIRMED" || documentStatus === "PENDING_APPROVAL",
    confirmedAt: document.confirmed_at ?? null,
  });

  // The explicit discard goes through the release door, which anyone with
  // access to the document may use; the in-session cancel is the holder's
  // alone. Releasing rolls the session's scans back, so it invalidates what the
  // document says about them — the same key the receiving view clears when
  // it cancels, and the prefix that carries this notice's own query.
  const closeSession = useAppMutation<void, void>(
    async () => {
      if (!session) return;
      if (session.kind === "receiving") {
        await documentsReceivingApi.wmsReceivingRelease(documentId, session.id);
      } else {
        await documentsPickingApi.wmsPickingRelease(documentId, session.id);
      }
    },
    (qc) =>
      qc.invalidateQueries({
        queryKey: queryKeys.documents.detail(documentId),
      }),
    { errorFallback: t("scanSession.closeFailed") },
  );

  if (!session) return null;
  const progress = { done: session.doneLines, total: session.totalLines };
  if (session.status === "finished") {
    // Only a confirmed document can be completed from here; one waiting for
    // approval says so in its own card.
    if (documentStatus !== "CONFIRMED") return null;
    return (
      <FinishedScanNotice
        kind={session.kind}
        packed={isPackedType(document.type)}
        onComplete={onComplete}
        isCompletePending={isCompletePending}
        className={className}
      />
    );
  }

  // A paused session's scans are the document's answers: completion books
  // them and writes the rest as a shortage, so finishing needs no second
  // round of reasons. A dispatch still completes in its Packing step, and a
  // session somebody is scanning in is theirs to finish.
  const canCompleteWithScans =
    session.status === "paused" &&
    documentStatus === "CONFIRMED" &&
    !isPackedType(document.type);

  // Awaited, not fire-and-forget: the dialog stays open on a refusal and
  // shows the sentence, instead of closing on a click that changed nothing.
  const handleConfirmClose = async () => {
    await closeSession.mutateAsync();
    setConfirmOpen(false);
    toast.success(t("scanSession.closed"));
  };

  return (
    <div
      role="status"
      data-testid="open-scan-session-notice"
      className={cn(NOTICE_CLASS, className)}
    >
      <div className="flex items-start gap-2">
        <ScanLine size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
        <p className="font-medium">
          {session.kind === "receiving"
            ? t("scanSession.receiving", progress)
            : t("scanSession.picking", progress)}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="default"
          size="sm"
          onClick={
            session.kind === "receiving" ? onResumeReceiving : onResumePicking
          }
        >
          <ScanLine size={16} />
          {t("scanSession.continue", progress)}
        </Button>
        {canCompleteWithScans && (
          <Button
            variant="secondary"
            size="sm"
            isLoading={isCompletePending}
            onClick={() => onComplete()}
          >
            <CheckCircle2 size={16} />
            {t("scanSession.complete")}
          </Button>
        )}
        <Button
          variant="ghostDanger"
          size="sm"
          onClick={() => setConfirmOpen(true)}
        >
          <X size={16} />
          {t("scanSession.close")}
        </Button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title={t("scanSession.closeTitle")}
        message={t("scanSession.closeMessage")}
        confirmLabel={t("scanSession.closeConfirm")}
        variant="danger"
        errorFallback={t("scanSession.closeFailed")}
        onConfirm={handleConfirmClose}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

const NOTICE_CLASS =
  "flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-on-warning dark:border-amber-800/60 dark:bg-amber-500/10";

/**
 * A scan that ended over a document nobody completed. A dispatch completes
 * in its Packing step, which carries the shipment as well, so the notice
 * points there instead of offering a second completion beside it.
 */
function FinishedScanNotice({
  kind,
  packed,
  onComplete,
  isCompletePending,
  className,
}: {
  kind: ScanSessionKind;
  packed: boolean;
  onComplete: () => void;
  isCompletePending: boolean;
  className?: string;
}) {
  const { t } = useTranslation("warehouse");
  const sentence =
    kind === "receiving"
      ? t("scanSession.finishedReceiving")
      : packed
        ? t("scanSession.finishedPacking")
        : t("scanSession.finishedPicking");
  return (
    <div
      role="status"
      data-testid="unbooked-scan-session-notice"
      className={cn(NOTICE_CLASS, className)}
    >
      <div className="flex items-start gap-2">
        <ScanLine size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
        <p className="font-medium">{sentence}</p>
      </div>
      {!packed && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="default"
            size="sm"
            isLoading={isCompletePending}
            onClick={() => onComplete()}
          >
            <CheckCircle2 size={16} />
            {t("scanSession.complete")}
          </Button>
        </div>
      )}
    </div>
  );
}
