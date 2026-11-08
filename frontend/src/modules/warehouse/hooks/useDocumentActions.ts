import { useExecuteDoor } from "@/modules/warehouse/hooks/useExecuteDoor";
import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  extractApiError,
  extractApiErrorCode,
  extractApiErrorField,
} from "@/lib/errors";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import { downloadDocumentPdf } from "@/modules/warehouse/lib/downloadDocumentPdf";
import {
  UNDOABLE_DOCUMENT_TYPES,
  undoLabelKey,
  type DocumentCompletePayload,
  type DocumentTrackingPayload,
  type WarehouseDocument,
} from "@/modules/warehouse/types";
import { useHandedOverCompletion } from "./usePickingHandOff";
import { useReceiptExpiryQuestion } from "./useReceiptExpiryQuestion";

/** Which irreversible step the detail page's confirm dialog is asking about. */
export type ConfirmAction =
  "confirm" | "cancel" | "delete" | "postNow" | "undo" | null;

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** Copy the document and take the reader to it; a refusal keeps its own words. */
async function duplicateDocument(
  doc: WarehouseDocument | undefined,
  context: {
    mutateAsync: (id: string) => Promise<WarehouseDocument>;
    navigate: (path: string) => void;
    t: Translate;
  },
): Promise<void> {
  if (!doc) return;
  try {
    const copy = await context.mutateAsync(doc.id);
    toast.success(
      context.t("actions.duplicateSuccess", {
        number: documentTitle(context.t, copy),
      }),
    );
    context.navigate(`/warehouse/documents/${copy.id}`);
  } catch (error: unknown) {
    // The refusal this call got, not the page query's `error` — a 403 here
    // says "you may not duplicate", and replacing it with our own "failed
    // to duplicate" left the reader unable to tell that from a malfunction.
    toast.error(extractApiError(error, context.t("actions.duplicateError")));
  }
}

/**
 * Reverse a just-posted document, from the success toast or the header.
 *
 * The server writes and posts the reversal in one call. A profile that puts
 * an approval in front of the reversal answers PENDING_APPROVAL instead —
 * the stock moves when the approval is granted, and the toast says so rather
 * than claiming it is done.
 *
 * A refusal means later movements used the stock up. The server's sentence
 * names what blocks it and points at a correction; the toast offers the form
 * that writes one.
 */
function undoDocument(
  id: string,
  context: {
    mutate: (
      id: string,
      opts?: {
        onSuccess?: (data?: WarehouseDocument) => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    navigate: (path: string) => void;
    onOpenCorrection?: () => void;
    t: Translate;
  },
): void {
  context.mutate(id, {
    onSuccess: (reversal) => {
      if (reversal?.status === "PENDING_APPROVAL") {
        toast.success(
          context.t("toast.undoPendingApproval", {
            number: reversal.number ?? "",
          }),
        );
        return;
      }
      toast.success(
        context.t("toast.undone", { number: reversal?.number ?? "" }),
        {
          action: reversal
            ? {
                label: context.t("actions.viewReversal"),
                onClick: () =>
                  context.navigate(`/warehouse/documents/${reversal.id}`),
              }
            : undefined,
        },
      );
    },
    onError: (err) => {
      toast.error(extractApiError(err, context.t("errors.undoFailed")), {
        action: context.onOpenCorrection
          ? {
              label: context.t("actions.correct"),
              onClick: context.onOpenCorrection,
            }
          : undefined,
      });
    },
  });
}

/**
 * The answer to a completed document, wherever the completion came from.
 *
 * A short receipt leaves a backorder behind, and the toast carries its
 * number and a link — otherwise the only trace is a banner on the document
 * page the worker may never reopen. A full posting offers Undo instead: the
 * way back from a typo has to sit where the confirmation that it worked
 * appears, not only on a page the worker may never reopen.
 */
function announceCompletion(
  completed: WarehouseDocument | undefined,
  context: {
    navigate: (path: string) => void;
    runUndo: (id: string) => void;
    t: Translate;
    setExecutionOpen: (open: boolean) => void;
  },
): void {
  if (completed?.generated_backorder_id) {
    toast.success(
      context.t("backorder.createdToast", {
        number: completed.generated_backorder_number ?? "",
      }),
      {
        action: {
          label: context.t("backorder.viewBackorder"),
          onClick: () =>
            context.navigate(
              `/warehouse/documents/${completed.generated_backorder_id}`,
            ),
        },
      },
    );
  } else {
    const canUndo =
      completed !== undefined &&
      completed.status === "COMPLETED" &&
      UNDOABLE_DOCUMENT_TYPES.has(completed.type) &&
      !completed.reversed_by_id;
    if (canUndo && completed) {
      toast.success(context.t("toast.completed"), {
        action: {
          label: context.t(undoLabelKey(completed.type)),
          onClick: () => context.runUndo(completed.id),
        },
      });
    } else {
      toast.success(context.t("toast.completed"));
    }
  }
  context.setExecutionOpen(false);
}

interface UseDocumentActionsProps {
  docId: string | undefined;
  /** The document the page shows — what the PDF is built from. */
  doc?: WarehouseDocument;
  /** Current document status — a CONFIRMED correction re-applies without
   * re-confirming (retry path). */
  docStatus?: string;
  /** Duplicate the document; the hook moves the reader to the copy. */
  duplicateMutation: {
    mutateAsync: (id: string) => Promise<WarehouseDocument>;
  };
  confirmMutation: {
    mutate: (
      id: string,
      opts?: {
        onSuccess?: (data?: WarehouseDocument) => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    isPending: boolean;
  };
  /** The one-step action: confirm and post the draft in one call. */
  postNowMutation: {
    mutate: (
      payload: { id: string; data?: DocumentTrackingPayload },
      opts?: {
        onSuccess?: (data?: WarehouseDocument) => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    isPending: boolean;
  };
  completeMutation: {
    mutate: (
      payload: { id: string; data?: DocumentCompletePayload },
      opts?: {
        onSuccess?: (data?: WarehouseDocument) => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    isPending: boolean;
  };
  cancelMutation: {
    mutate: (
      id: string,
      opts?: {
        onSuccess?: () => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    isPending: boolean;
  };
  deleteMutation: {
    mutate: (
      id: string,
      opts?: {
        onSuccess?: () => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    isPending: boolean;
  };
  /** Reverse a just-posted document; answers with the reversal it wrote. */
  undoMutation: {
    mutate: (
      id: string,
      opts?: {
        onSuccess?: (data?: WarehouseDocument) => void;
        onError?: (err: unknown) => void;
      },
    ) => void;
    isPending: boolean;
  };
  /** Open the correction form — where a refused undo sends the reader. */
  onOpenCorrection?: () => void;
}

export function useDocumentActions({
  docId,
  doc,
  docStatus,
  duplicateMutation,
  confirmMutation,
  postNowMutation,
  completeMutation,
  cancelMutation,
  deleteMutation,
  undoMutation,
  onOpenCorrection,
}: UseDocumentActionsProps) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [isPdfDownloading, setIsPdfDownloading] = useState(false);
  const [executionOpen, setExecutionOpen] = useState(false);
  const door = useExecuteDoor(doc, executionOpen, setExecutionOpen);

  const handleDownloadPdf = useCallback(() => {
    void downloadDocumentPdf(doc, t, setIsPdfDownloading);
  }, [doc, t]);

  const duplicateMutateAsync = duplicateMutation.mutateAsync;
  const handleDuplicate = useCallback(
    () =>
      duplicateDocument(doc, {
        mutateAsync: duplicateMutateAsync,
        navigate,
        t,
      }),
    [doc, duplicateMutateAsync, navigate, t],
  );

  const undoMutate = undoMutation.mutate;
  const runUndo = useCallback(
    (id: string) =>
      undoDocument(id, {
        mutate: undoMutate,
        navigate,
        onOpenCorrection,
        t,
      }),
    [undoMutate, navigate, onOpenCorrection, t],
  );

  const reportCompletion = useCallback(
    (completed?: WarehouseDocument) =>
      announceCompletion(completed, {
        navigate,
        runUndo,
        t,
        setExecutionOpen,
      }),
    [navigate, runUndo, t],
  );

  const reportPostNow = useCallback(
    (data?: WarehouseDocument) => {
      // The one-step action posts the stock, or — where the profile
      // requires it — parks the document for an approval that posts it
      // when granted. Neither reads as the other.
      if (data?.status === "PENDING_APPROVAL") {
        toast.success(t("toast.pendingApproval"));
      } else {
        reportCompletion(data);
      }
      setConfirmAction(null);
    },
    [reportCompletion, t],
  );

  // A record kept in another unit than the card its door adopts stops the
  // completion with RECORD_UNIT_MISMATCH, naming the record and both units.
  // The refusal is a question, not a verdict: the dialog built on this state
  // offers the confirmation, and the retry carries it on the same payload.
  const [unitMismatch, setUnitMismatch] = useState<{
    product: string;
    templateUnit: string;
    chosenUnit: string;
    payload: DocumentCompletePayload;
  } | null>(null);

  const handleCompletionRefused = useCallback(
    (err: unknown, payload: DocumentCompletePayload) => {
      if (extractApiErrorCode(err) === "RECORD_UNIT_MISMATCH") {
        setUnitMismatch({
          product: extractApiErrorField(err, "product") ?? "",
          templateUnit: extractApiErrorField(err, "template_unit") ?? "",
          chosenUnit: extractApiErrorField(err, "chosen_unit") ?? "",
          payload,
        });
        return;
      }
      toast.error(extractApiError(err, t("errors.completeFailed")));
    },
    [t],
  );

  const handlePostNowRefused = useCallback(
    (err: unknown) => {
      toast.error(extractApiError(err, t("errors.postNowFailed")));
      setConfirmAction(null);
    },
    [t],
  );

  const expiryQuestion = useReceiptExpiryQuestion({
    doc,
    docId,
    complete: completeMutation.mutate,
    postNow: postNowMutation.mutate,
    onCompleted: reportCompletion,
    onPosted: reportPostNow,
    onCompletionRefused: handleCompletionRefused,
    onPostingRefused: handlePostNowRefused,
  });

  const handleCompletionError = expiryQuestion.handleCompletionError;

  const handlePostNowError = useCallback(
    (err: unknown) => {
      // The question takes over from the confirmation the reader just gave;
      // answering it posts the same draft.
      if (expiryQuestion.askFromError("post", {}, err)) {
        setConfirmAction(null);
        return;
      }
      handlePostNowRefused(err);
    },
    [expiryQuestion, handlePostNowRefused],
  );

  const handleAction = useCallback(() => {
    if (!confirmAction || !docId) return;
    // Undo answers with the reversal document, not the original: it speaks
    // its own sentence and offers a link to the correction it wrote.
    if (confirmAction === "undo") {
      setConfirmAction(null);
      runUndo(docId);
      return;
    }
    if (confirmAction === "postNow") {
      postNowMutation.mutate(
        { id: docId },
        { onSuccess: reportPostNow, onError: handlePostNowError },
      );
      return;
    }
    const mutationMap = {
      confirm: confirmMutation,
      cancel: cancelMutation,
      delete: deleteMutation,
    };
    const toastMap = {
      confirm: {
        success: t("toast.confirmed"),
        error: t("errors.confirmFailed"),
      },
      cancel: {
        success: t("toast.cancelled"),
        error: t("errors.cancelFailed"),
      },
      delete: {
        success: t("toast.deleted"),
        error: t("errors.deleteFailed"),
      },
    };
    mutationMap[confirmAction].mutate(docId, {
      onSuccess: (data) => {
        // A confirm over the approval threshold parks the document in
        // PENDING_APPROVAL instead of CONFIRMED — surface that distinctly
        // rather than the misleading "ready for execution" toast.
        if (
          confirmAction === "confirm" &&
          data?.status === "PENDING_APPROVAL"
        ) {
          toast.success(t("toast.pendingApproval"));
        } else {
          toast.success(toastMap[confirmAction].success);
        }
        setConfirmAction(null);
        if (confirmAction === "delete") {
          navigate("/warehouse");
        }
      },
      onError: (err) => {
        toast.error(extractApiError(err, toastMap[confirmAction].error));
        setConfirmAction(null);
      },
    });
  }, [
    confirmAction,
    docId,
    confirmMutation,
    postNowMutation,
    cancelMutation,
    deleteMutation,
    reportPostNow,
    handlePostNowError,
    runUndo,
    navigate,
    t,
  ]);

  const confirmMutate = confirmMutation.mutate;
  const completeMutate = completeMutation.mutate;

  // the backend reports a missing correction item with a stable code
  // and the product name — translate client-side instead of echoing the
  // server's English sentence verbatim.
  const showCorrectionCompleteError = useCallback(
    (err: unknown) => {
      if (extractApiErrorCode(err) === "CORRECTION_ITEM_MISSING") {
        const product = extractApiErrorField(err, "product") ?? "";
        toast.error(t("errors.correctionItemMissing", { product }));
        return;
      }
      // a correction carries no execution payload, so the retry carries
      // only the confirmation
      if (extractApiErrorCode(err) === "RECORD_UNIT_MISMATCH") {
        setUnitMismatch({
          product: extractApiErrorField(err, "product") ?? "",
          templateUnit: extractApiErrorField(err, "template_unit") ?? "",
          chosenUnit: extractApiErrorField(err, "chosen_unit") ?? "",
          payload: {},
        });
        return;
      }
      toast.error(extractApiError(err, t("errors.completeFailed")));
    },
    [t],
  );

  const dismissUnitMismatch = useCallback(() => setUnitMismatch(null), []);

  const confirmUnitChoice = useCallback(() => {
    if (!docId || !unitMismatch) return;
    const { payload } = unitMismatch;
    const confirmed = { ...payload, unit_confirmed_over_template: true };
    setUnitMismatch(null);
    completeMutate(
      { id: docId, data: confirmed },
      {
        onSuccess: reportCompletion,
        // The retry can stop on the next question — the expiry of a FEFO
        // line — so it answers through the same handler as the first call.
        onError: (err) => handleCompletionError(err, confirmed),
      },
    );
  }, [
    docId,
    unitMismatch,
    completeMutate,
    reportCompletion,
    handleCompletionError,
  ]);

  const handleApplyCorrection = useCallback(() => {
    if (!docId) return;
    const completeCorrection = () =>
      completeMutate(
        { id: docId },
        {
          onSuccess: () => toast.success(t("toast.correctionApplied")),
          onError: showCorrectionCompleteError,
        },
      );
    // a failed first attempt leaves the correction CONFIRMED — retry
    // must re-run the completion only, not confirm again.
    if (docStatus === "CONFIRMED") {
      completeCorrection();
      return;
    }
    confirmMutate(docId, {
      onSuccess: completeCorrection,
      onError: (err) =>
        toast.error(extractApiError(err, t("errors.confirmFailed"))),
    });
    // Depend on the stable ``mutate`` function references, not the
    // mutation result objects — those are recreated every render and
    // would make this callback unstable for consumers' effect deps.
  }, [
    docId,
    docStatus,
    confirmMutate,
    completeMutate,
    showCorrectionCompleteError,
    t,
  ]);

  const handleComplete = useCallback(
    (data: DocumentCompletePayload) => {
      if (!docId) return;
      completeMutation.mutate(
        { id: docId, data },
        {
          onSuccess: reportCompletion,
          onError: (err) => handleCompletionError(err, data),
        },
      );
    },
    [docId, completeMutation, reportCompletion, handleCompletionError],
  );

  /**
   * Close a document a scanning session has already finished.
   *
   * The session wrote what arrived onto the document's lines before the
   * page heard about it, so no execution payload travels here — a payload
   * names the lines it answers for and books every other line as delivered
   * in full, which would erase the shortfall the backorder exists for. The
   * payload-free door used to be silent: the numbers and the backorder the
   * server answered with were dropped, and the worker who just closed the
   * session was the last to know a shortage had been posted.
   *
   * A dispatch's shipment may ride along: a body that names no line books
   * the lines the way no body does.
   */
  const handleSessionComplete = useCallback(
    (shipment?: ShipmentCreate) => {
      if (!docId) return;
      const payload: DocumentCompletePayload = shipment ? { shipment } : {};
      completeMutation.mutate(
        { id: docId, data: shipment ? payload : undefined },
        {
          onSuccess: reportCompletion,
          // A refusal that is a question — a line still undated, a record in
          // another unit — is answered on the payload the retry builds from
          // the document's own quantities; the others reach the reader.
          onError: (err) => handleCompletionError(err, payload),
        },
      );
    },
    [docId, completeMutation, reportCompletion, handleCompletionError],
  );
  // A list's picking sheet that ended over this one document handed its
  // completion here, with the carrier its summary took.
  useHandedOverCompletion(doc, handleSessionComplete);

  return {
    confirmAction,
    setConfirmAction,
    handleAction,
    handleApplyCorrection,
    handleComplete,
    handleSessionComplete,
    isUndoPending: undoMutation.isPending,
    executionOpen,
    door,
    setExecutionOpen,
    isPdfDownloading,
    handleDownloadPdf,
    handleDuplicate,
    unitMismatch,
    confirmUnitChoice,
    dismissUnitMismatch,
    // The line whose date the door is waiting for, and the two ways to
    // answer it — the same shape for a completion and a one-step posting.
    receiptExpiry: expiryQuestion.prompt,
  };
}
