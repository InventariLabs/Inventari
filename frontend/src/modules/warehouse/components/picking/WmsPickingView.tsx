import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import LoadingSpinner from "@/components/LoadingSpinner";
import { WmsStartFailure } from "@/modules/warehouse/components/WmsStartFailure";
import { queryKeys } from "@/hooks/queries/keys";
import { extractApiError } from "@/lib/errors";
import { useWmsPicking } from "@/modules/warehouse/hooks/useWmsPicking";
import type { WmsPickingFailureContext } from "@/modules/warehouse/hooks/useWmsPicking";
import WmsPickCoverageGate from "./WmsPickCoverageGate";
import WmsPickingActive from "./WmsPickingActive";
import { WmsSkipConfirm } from "../WmsSkipConfirm";
import WmsPickingSummary from "./WmsPickingSummary";
import WmsShortPickDialog from "./WmsShortPickDialog";
import type { WmsPickLine } from "@/modules/warehouse/api/documents";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import { unitLabel } from "@/lib/i18nHelpers";
import type { ShipmentDraft } from "../shipping/shipmentDraft";
import { buzzRefusal } from "../refusalBuzz";
import { pickRefusal } from "./pickRefusal";

interface Props {
  documentId: string;
  /** Picks these dispatches in one session; `documentId` is the first. */
  documentIds?: string[];
  onClose: (completed?: boolean, shipment?: ShipmentCreate) => void;
  /** Invoked when the session start was blocked by the approval engine. */
  onRequestApproval?: () => void | Promise<void>;
  /** Offered on the summary of a dispatch: close without completing, to pack. */
  onPack?: (shipment: ShipmentDraft) => void;
}

// A line holding no batch has none to promise: say so instead of "it expects ".
function wrongLotMessage(t: TFunction, code: string, lot?: string | null) {
  return lot
    ? t("picking.toast.wrong_lot", { code, lot })
    : t("picking.toast.wrong_lot_unplanned", { code });
}

// The line a scan and the quantity dialog both report when something was picked.
function announcePicked(
  t: TFunction,
  result: {
    product_name: string | null;
    picked_quantity: number;
    uom_symbol: string | null;
  },
) {
  toast.success(
    t("picking.toast.picked", {
      product: result.product_name ?? "",
      qty: result.picked_quantity,
      uom: unitLabel(t, result.uom_symbol),
    }),
  );
}

// What a failed action says when the API offered no sentence of its own —
// a 5xx leaves the hook with nothing worth quoting. One entry per action
// the hook can name, each spelled out so the i18n gate reads the call
// sites; a hard-coded fallback in the hook was an English sentence on a
// Polish screen.
function failureSentence(t: TFunction, context: WmsPickingFailureContext) {
  const sentences: Record<WmsPickingFailureContext, string> = {
    scan: t("picking.error.scan_failed"),
    short_pick: t("picking.error.short_pick_failed"),
    skip: t("picking.error.skip_failed"),
    undo: t("picking.error.undo_failed"),
    complete: t("picking.error.complete_failed"),
    cancel: t("picking.error.cancel_failed"),
  };
  return sentences[context];
}

// What a scan's answer says to the picker, one toast per status.
function announceScan(
  t: TFunction,
  result: Awaited<ReturnType<ReturnType<typeof useWmsPicking>["scan"]>>,
  barcode: string,
  lotName?: string,
) {
  if (!result) return;
  if (result.status === "picked") {
    announcePicked(t, result);
    // The scan named another batch than the row promised: it is booked
    // as picked, and the picker is told which one the plan meant.
    if (result.planned_lot_name) {
      toast.warning(
        t("picking.toast.lot_changed", {
          lot: result.lot_name ?? "",
          planned: result.planned_lot_name,
        }),
      );
    }
  } else if (result.status === "wrong_lot") {
    toast.error(wrongLotMessage(t, lotName ?? "", result.lot_name));
  } else if (result.status === "lot_too_small") {
    toast.error(
      t("picking.toast.lot_too_small", { lot: result.lot_name ?? "" }),
    );
  } else if (result.status === "shelf_confirmed") {
    toast.success(
      t("picking.toast.shelf_confirmed", { location: result.shelf }),
    );
  } else if (result.status === "shelf_required") {
    toast.error(t("picking.toast.shelf_required", { location: result.shelf }));
  } else if (result.status === "wrong_shelf") {
    toast.error(t("picking.toast.wrong_shelf", { location: result.shelf }));
  } else if (result.status === "not_found") {
    // A code no product carries: name it, and the place a worker gives a
    // product its code — the terminal has no way to do that itself.
    toast.error(t("picking.toast.not_found", { code: barcode }), {
      description: t("picking.toast.not_found_hint"),
    });
  } else if (result.status === "over_quantity") {
    toast.error(
      t("picking.toast.over_quantity", {
        qty: result.picked_quantity,
        expected: result.expected_quantity,
        uom: unitLabel(t, result.uom_symbol),
      }),
    );
  } else if (result.status === "rejected") {
    toast.error(t("picking.toast.document_closed"));
  } else if (result.status === "all_picked") {
    toast(t("picking.toast.all_picked"));
  } else if (
    result.status === "not_in_document" ||
    result.status === "already_picked" ||
    result.status === "line_skipped" ||
    result.status === "short_pick_confirmed"
  ) {
    // Refusals are shown beside the field; short picks use their own handler.
  } else {
    const unhandled: never = result.status;
    return unhandled;
  }
}

// What a session that would not start says. The API's own sentence when it
// gave one (a 4xx carries a translated one, e.g. "another user has an active
// picking session"); the generic line when it did not, which is what a 500
// leaves behind.
function startFailureMessage(
  t: TFunction,
  heldSession: { holderName: string } | null,
  errorCode: string | null,
  errorStatus: number,
  error: string | null,
) {
  if (heldSession !== null) {
    return t("picking.error.session_held", { owner: heldSession.holderName });
  }
  if (errorCode === "APPROVAL_REQUIRED") {
    return t("picking.error.approval_required");
  }
  if (errorStatus === 403) return t("picking.error.refused");
  return error ?? t("picking.error.start_failed");
}

function WmsPickingView({
  documentId,
  documentIds,
  onClose,
  onRequestApproval,
  onPack,
}: Props) {
  const { t } = useTranslation("warehouse");
  const {
    state,
    isLoading,
    error,
    errorCode,
    errorStatus,
    errorContext,
    heldSession,
    releaseHeldSession,
    takeOverHeldSession,
    startSession,
    scan,
    confirmShortPick,
    skipLine,
    undoLine,
    completeSession,
    cancelSession,
    requestShortPick,
    cancelShortPick,
    reset,
  } = useWmsPicking(documentId, documentIds);

  const sessionError =
    error ?? (errorContext ? failureSentence(t, errorContext) : null);

  const queryClient = useQueryClient();

  // guard against React StrictMode double-invoking the mount effect
  // in dev — a second start fails with "session already exists". Receiving has
  // carried this guard since; picking did not.
  const startedRef = useRef(false);

  useEffect(() => {
    if (state.phase === "idle" && !startedRef.current) {
      startedRef.current = true;
      startSession();
    }
  }, [state.phase, startSession]);

  // A finished picking session changes the document's done quantities. The
  // receiving view refreshed the detail behind it; this one left the reader
  // looking at "Done 0 / Planned N" until a reload.
  const invalidateDocument = () => {
    queryClient.invalidateQueries({
      // The register behind a multi-document session shows every one of them.
      queryKey: documentIds
        ? queryKeys.documents.all
        : queryKeys.documents.detail(documentId),
    });
  };

  // The last scan can end the session with no handler here, and the summary's
  // links would open the documents as cached from before the picking.
  useEffect(() => {
    if (state.phase === "completed") {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
    }
  }, [state.phase, queryClient]);

  // When the start was refused because someone else's session holds the
  // document, the dialog offers two ways out: take the session over with the
  // scans already made, or put the holder's scans back. Either way the
  // reader's own session starts next. Without them the refusal is a dead
  // end — the document waits for a holder who walked away.
  const handleHeldSession = async (act: () => Promise<unknown>) => {
    const failure = await act();
    if (failure !== null) {
      toast.error(extractApiError(failure, t("picking.error.start_failed")));
      return;
    }
    invalidateDocument();
    startSession();
  };

  // The last scan the dispatch refused, said beside the scan field.
  const [refusal, setRefusal] = useState<string | null>(null);

  const handleScan = async (
    barcode: string,
    quantity: number,
    lotName?: string,
  ) => {
    const result = await scan(barcode, quantity, lotName);
    if (result?.status === "rejected") invalidateDocument();
    // Said beside the scan field and kept until the next scan answers.
    const refusal = pickRefusal(t, result);
    setRefusal(refusal);
    if (refusal) buzzRefusal();
    announceScan(t, result, barcode, lotName);
  };

  const handleUndoLine = async (line: WmsPickLine) => {
    const undone = await undoLine(line.id);
    // Only when the server undid it. A refused undo answers with its own
    // sentence — a package already holds the goods — and the white toast
    // used to fire beside the red refusal.
    if (undone)
      toast(t("picking.toast.undo", { product: line.product_name ?? "" }));
  };

  const handleShortPickConfirm = async (
    lineId: string,
    pickedQty: number,
    code?: string,
    reason?: string,
    replaceScans?: boolean,
  ) => {
    const result = await confirmShortPick(
      lineId,
      pickedQty,
      code,
      reason,
      replaceScans,
    );
    // Nothing to announce when the server refused the quantity — the
    // success toast used to fire beside the error. And a full pick made
    // through this dialog reports what a scan would report, not a
    // shortage nobody had.
    if (!result) return;
    if (result.status === "shelf_required") {
      toast.error(
        t("picking.toast.shelf_required", { location: result.shelf }),
      );
    } else if (result.status === "picked") {
      announcePicked(t, result);
    } else {
      toast(t("picking.toast.short_confirmed"));
    }
  };

  // The whole line in one tap, the receiving session's "Receive full
  // amount": the number is the document's own expectation, and no
  // discrepancy travels with it — a full pick carries none. It goes
  // through the same door as the shortfall form because that door is what
  // books a quantity without a scan, and it reports what a scan would.
  const handleFullPick = (line: WmsPickLine) => {
    void handleShortPickConfirm(line.id, Number(line.expected_quantity));
  };

  // A skip leaves the line unpicked and is one tap from the row, so it asks
  // first. It asks no reason, unlike a short pick: the server keeps none for
  // a skip, and the line stays on the list with an Undo.
  const [skipAsk, setSkipAsk] = useState<WmsPickLine | null>(null);

  const handleSkipLine = async (lineId: string) => {
    // Same answer as Undo: the server may refuse the skip — a package
    // already holds what the line picked — and the toast follows it.
    const skipped = await skipLine(lineId);
    if (skipped) toast(t("picking.toast.skipped"));
  };

  const handleComplete = async () => {
    const closed = await completeSession();
    invalidateDocument();
    // Only when the server closed it. The refusal it answers with — "Cannot
    // complete: 1 lines still pending" — used to arrive under a green
    // "completed", and the reader had two contradictory sentences and no way
    // to tell which one was true.
    if (closed) toast.success(t("picking.toast.completed"));
  };

  const handleCancel = async () => {
    const cancelled = await cancelSession();
    invalidateDocument();
    // A refused cancel leaves the session open server-side: keep the sheet
    // and the refusal sentence, and reset() would wipe both.
    if (!cancelled) return;
    reset();
    onClose();
  };

  const handleClose = () => {
    // Closing the sheet is not a decision to put anything back: the scans
    // already recorded stay counted server-side, and the next start hands
    // this session back — the resume the browser's back arrow always had.
    // Putting things back is the named Cancel button's job.
    invalidateDocument();
    reset();
    onClose();
  };

  if (state.phase === "idle") {
    // the start can fail (e.g. 409 APPROVAL_REQUIRED) while the
    // phase stays "idle" — surface that instead of rendering a blank view.
    // `errorStatus`, not `error`: the message is what the API said and a 500
    // says nothing worth showing, so it is legitimately absent. Branching on
    // it would put a blank view back exactly where the failure is hardest to
    // explain.
    if (errorStatus !== null) {
      const isApprovalRequired = errorCode === "APPROVAL_REQUIRED";
      const refused = errorStatus === 403;
      return (
        <WmsStartFailure
          message={startFailureMessage(
            t,
            heldSession,
            errorCode,
            errorStatus,
            error,
          )}
          dialogLabel={t("picking.title")}
          closeLabel={t("picking.close")}
          onClose={() => onClose()}
          refused={refused || heldSession !== null}
          heldSession={
            heldSession === null
              ? undefined
              : {
                  owner: heldSession.holderName,
                  onTakeOver: () => handleHeldSession(takeOverHeldSession),
                  onRelease: () => handleHeldSession(releaseHeldSession),
                }
          }
          retry={
            isApprovalRequired || refused || heldSession !== null
              ? undefined
              : { label: t("picking.error.retry"), onRetry: startSession }
          }
          requestApproval={
            isApprovalRequired && onRequestApproval
              ? {
                  label: t("picking.error.request_approval"),
                  onRequest: onRequestApproval,
                }
              : undefined
          }
        />
      );
    }
    if (isLoading) {
      return (
        <div className="flex justify-center py-10">
          <LoadingSpinner />
        </div>
      );
    }
    return null;
  }

  if (state.phase === "completed" && state.session) {
    // Closing completes the page's document only when the session is that
    // one document's: a session over several leaves each to be packed and
    // completed on its own, however it was opened.
    const completesDocument =
      !documentIds && state.session.documents.length <= 1;
    // The last scan can close the session by itself and nothing has refreshed
    // the document since: a register behind a multi-document session has no
    // handler that refreshes its rows, and the Pack step reads the picked
    // quantities from the document.
    const leave = (then: () => void) => {
      invalidateDocument();
      reset();
      then();
    };
    return (
      <WmsPickingSummary
        session={state.session}
        lines={state.lines}
        completesDocument={completesDocument}
        onUndoSkip={(line) => void handleUndoLine(line)}
        onAnswerSkip={(line, code) => void confirmShortPick(line.id, 0, code)}
        isLoading={isLoading}
        error={sessionError}
        onClose={(shipment) =>
          leave(() => onClose(completesDocument, shipment))
        }
        // Left without completing: the document keeps what was picked and
        // waits, as picked, for its Pack step or its own Complete.
        onLeave={() => leave(() => onClose(false))}
        onPack={onPack && ((shipment) => leave(() => onPack(shipment)))}
      />
    );
  }

  if (state.phase === "cancelled") {
    return null;
  }

  return (
    <div className="relative">
      <WmsPickingActive
        session={state.session!}
        lines={state.lines}
        isLoading={isLoading}
        error={sessionError}
        refusal={refusal}
        onScan={handleScan}
        onFullPick={handleFullPick}
        onUndoLine={handleUndoLine}
        onShortPick={(line) => requestShortPick(line.id)}
        onSkipLine={setSkipAsk}
        onComplete={handleComplete}
        onCancel={handleCancel}
        onClose={handleClose}
      />

      <WmsSkipConfirm
        line={skipAsk}
        title={t("picking.skip_confirm_title")}
        message={(product) => t("picking.skip_confirm_message", { product })}
        confirmLabel={t("picking.skip_line")}
        onConfirm={(line) => {
          setSkipAsk(null);
          void handleSkipLine(line.id);
        }}
        onCancel={() => setSkipAsk(null)}
      />

      {state.phase === "short_pick" && state.shortPickLine && (
        <WmsShortPickDialog
          line={state.shortPickLine}
          isLoading={isLoading}
          onConfirm={handleShortPickConfirm}
          onCancel={cancelShortPick}
        />
      )}
    </div>
  );
}

/**
 * Opens the picking sheet once stock has been asked what it cannot cover.
 * The session starts over the dispatches that came through the gate: all of
 * the selection, or only those the person kept after seeing what was short.
 */
export default function WmsPickingWithCoverage(props: Props) {
  const [chosen, setChosen] = useState<string[] | null>(null);
  if (chosen === null) {
    return (
      <WmsPickCoverageGate
        documentIds={props.documentIds ?? [props.documentId]}
        onReady={setChosen}
        onClose={() => props.onClose()}
      />
    );
  }
  return (
    <WmsPickingView
      {...props}
      documentId={chosen[0]}
      documentIds={props.documentIds && chosen}
    />
  );
}
