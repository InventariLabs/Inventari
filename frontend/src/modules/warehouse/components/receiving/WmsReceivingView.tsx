import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import LoadingSpinner from "@/components/LoadingSpinner";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { WmsStartFailure } from "@/modules/warehouse/components/WmsStartFailure";
import { queryKeys } from "@/hooks/queries/keys";
import { extractApiError } from "@/lib/errors";
import { useWmsReceiving } from "@/modules/warehouse/hooks/useWmsReceiving";
import type { WmsReceivingFailureContext } from "@/modules/warehouse/hooks/useWmsReceiving";
import WmsReceivingActive from "./WmsReceivingActive";
import WmsReceivingPhone from "./WmsReceivingPhone";
import WmsReceivingPhoneDone from "./WmsReceivingPhoneDone";
import { WmsSkipConfirm } from "../WmsSkipConfirm";
import { useSurplusQuestion } from "../SurplusQuestion";
import WmsReceivingSummary from "./WmsReceivingSummary";
import WmsShortReceiveDialog from "./WmsShortReceiveDialog";
import WmsLotExpiryDialog from "./WmsLotExpiryDialog";
import { announceScanResult, receivingRefusal } from "./announceScanResult";
import type {
  WmsReceiveLine,
  WmsReceiveScanResult,
} from "@/modules/warehouse/api/documents_receiving";
import { useLocationsById } from "@/module-sdk";
import { locationChoiceOf } from "@/modules/warehouse/locationChoices";
import { useSetLineTarget } from "@/modules/warehouse/hooks/useDocuments";
import { unitLabel } from "@/lib/i18nHelpers";
import { useMediaQuery } from "@/hooks/useMediaQuery";

/** Below `sm` the session is worked one item at a time, as a phone holds it. */
const PHONE_QUERY = "(max-width: 639px)";

interface Props {
  documentId: string;
  onClose: (completed?: boolean) => void;
  /** Invoked when the session start was blocked by the approval engine. */
  onRequestApproval?: () => void | Promise<void>;
}

/**
 * What the short-receive dialog's answer deserves as a toast.
 *
 * Success is claimed only for a quantity the server accepted: the success
 * toast used to fire beside the over-quantity error. A full receive through
 * this dialog gets the scan's own "received" toast, not "short receive
 * confirmed".
 */
function announceShortReceive(t: TFunction, result: WmsReceiveScanResult) {
  if (result.status === "shelf_required") {
    toast.error(
      t("receiving.toast.shelf_required", { location: result.shelf }),
    );
  } else if (result.status === "received") {
    toast.success(
      t("receiving.toast.received", {
        product: result.product_name ?? "",
        qty: result.received_quantity,
        uom: unitLabel(t, result.uom_symbol),
      }),
    );
  } else {
    toast(t("receiving.toast.short_confirmed"));
  }
}

/** A question the server asked before it would book a quantity, and the call to send again with the answer. */
interface LotExpiryAsk {
  productName: string | null;
  resend: (tracking: { batch_number?: string; expiry_date: string }) => void;
}

/**
 * Opening the short-receive sheet from the phone's card: the count already
 * set there is what the sheet starts from, instead of the scans.
 */
function useHeldFromCard(
  requestShortReceive: (lineId: string) => void,
  sheetLine: WmsReceiveLine | null,
) {
  const [counted, setCounted] = useState<{
    lineId: string;
    quantity: number;
  } | null>(null);
  return {
    open: (line: WmsReceiveLine, quantity: number) => {
      setCounted({ lineId: line.id, quantity });
      requestShortReceive(line.id);
    },
    quantity: counted?.lineId === sheetLine?.id ? counted?.quantity : undefined,
  };
}

/**
 * The line the short-receive sheet is open for. Both sheets share one layer
 * and this one is rendered later, so while the expiry question it raised is
 * open the sheet is not mounted: its resend holds the typed quantity, and
 * Cancel on the question brings the sheet back for a fresh try.
 */
function shortSheetLineFor(
  state: { phase: string; shortReceiveLine: WmsReceiveLine | null },
  ask: LotExpiryAsk | null,
): WmsReceiveLine | null {
  return state.phase === "short_receive" && !ask
    ? state.shortReceiveLine
    : null;
}

function LotExpiryAskDialog({
  ask,
  isLoading,
  serverError,
  onCancel,
}: {
  ask: LotExpiryAsk;
  isLoading: boolean;
  serverError: string | null;
  onCancel: () => void;
}) {
  return (
    <WmsLotExpiryDialog
      productName={ask.productName}
      isLoading={isLoading}
      serverError={serverError}
      onConfirm={(batchNumber, expiryDate) =>
        ask.resend({
          ...(batchNumber ? { batch_number: batchNumber } : {}),
          expiry_date: expiryDate,
        })
      }
      onCancel={onCancel}
    />
  );
}

/**
 * What a failed action says when the API offered no sentence of its own —
 * a 5xx leaves the hook with nothing worth quoting. One entry per action
 * the hook can name, each spelled out so the i18n gate reads the call
 * sites; a hard-coded fallback in the hook was an English sentence on a
 * Polish screen.
 */
function failureSentence(
  t: TFunction,
  context: WmsReceivingFailureContext,
): string {
  const sentences: Record<WmsReceivingFailureContext, string> = {
    scan: t("receiving.error.scan_failed"),
    short_receive: t("receiving.error.short_receive_failed"),
    skip: t("receiving.error.skip_failed"),
    undo: t("receiving.error.undo_failed"),
    complete: t("receiving.error.complete_failed"),
    cancel: t("receiving.error.cancel_failed"),
  };
  return sentences[context];
}

/**
 * The sheet a refused or failed start leaves: what stopped it, and the ways
 * out that failure offers — take over or release a held session, ask for an
 * approval, or try again.
 */
function ReceivingStartFailure({
  error,
  errorCode,
  errorStatus,
  holderName,
  onTakeOver,
  onRelease,
  onRetry,
  onRequestApproval,
  onClose,
}: {
  error: string | null;
  errorCode: string | null;
  errorStatus: number;
  /** Whose session holds the document, when that is why the start failed. */
  holderName: string | null;
  onTakeOver: () => Promise<void>;
  onRelease: () => Promise<void>;
  onRetry: () => void;
  onRequestApproval?: () => void | Promise<void>;
  onClose: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const isApprovalRequired = errorCode === "APPROVAL_REQUIRED";
  const refused = errorStatus === 403;
  return (
    <WmsStartFailure
      message={
        holderName !== null
          ? t("receiving.error.session_held", {
              owner: holderName,
            })
          : isApprovalRequired
            ? t("receiving.error.approval_required")
            : refused
              ? t("receiving.error.refused")
              : // The specific reason when the API gave one (e.g. "an
                // active receiving session already exists"), which for a 4xx is a
                // translated sentence; the generic line when it did not,
                // which is what a 500 leaves behind.
                (error ?? t("receiving.error.start_failed"))
      }
      dialogLabel={t("receiving.title")}
      // A plain close: the sheet's own Cancel button is the named path
      // that cancels, and a ghost button wearing its label offered a
      // cancellation that never happened.
      closeLabel={t("receiving.close")}
      onClose={onClose}
      refused={refused || holderName !== null}
      heldSession={
        holderName === null
          ? undefined
          : {
              owner: holderName,
              onTakeOver,
              onRelease,
            }
      }
      retry={
        isApprovalRequired || refused || holderName !== null
          ? undefined
          : { label: t("receiving.error.retry"), onRetry }
      }
      requestApproval={
        isApprovalRequired && onRequestApproval
          ? {
              label: t("receiving.error.request_approval"),
              onRequest: onRequestApproval,
            }
          : undefined
      }
    />
  );
}

/**
 * The shelves the lines name, and the call that aims a line at another.
 *
 * The floor names a shelf through the route the office page already had:
 * one endpoint validates the destination, one planner recomputes around
 * the choice, and the two screens cannot answer "where does this go"
 * differently. The shelf picker of a row searches a stock flow's set — what
 * may hold stock, never a place a module owns — so the floor cannot aim a
 * pallet at a server rack the office form would not offer either. The places
 * read here are only the ones the lines already name (their code, whether
 * anything stands below them), by id. *onAimed* refreshes
 * the session read, because the plan the rows show is computed on the
 * document's lines, not stored on theirs.
 */
function useFloorShelves(
  documentId: string,
  lines: WmsReceiveLine[],
  onAimed: () => void,
) {
  const { t } = useTranslation("warehouse");
  const { byId, isError, error, refetch } = useLocationsById(
    lines.flatMap((line) => [
      line.planned_location_id,
      line.suggested_location_id,
      line.target_location_id,
    ]),
  );
  const setLineTarget = useSetLineTarget();
  // Whether the shelf was named: the phone names its offer before the count,
  // and stops when refused — with the reason, said here: `mutateAsync` gets
  // no toast from the mutation factory.
  const aim = async (
    line: WmsReceiveLine,
    target: string | null,
  ): Promise<boolean> => {
    try {
      await setLineTarget.mutateAsync({
        docId: documentId,
        lineId: line.document_line_id,
        targetLocationId: target,
      });
    } catch (error) {
      toast.error(extractApiError(error, t("common:errors.actionFailed")));
      return false;
    }
    onAimed();
    return true;
  };
  return {
    choices: [...byId.values()].map(locationChoiceOf),
    tree: { isError, error, refetch },
    pending: setLineTarget.isPending,
    aim,
  };
}

/**
 * The question asked before a line is skipped, as the picking session asks
 * it, and the skip that follows. The server may refuse the skip, as it may
 * an undo, and the toast follows its answer.
 */
function useSkipAsk(skipLine: (lineId: string) => Promise<boolean>) {
  const { t } = useTranslation("warehouse");
  const [skipAsk, setSkipAsk] = useState<WmsReceiveLine | null>(null);
  const handleSkipLine = async (lineId: string) => {
    const skipped = await skipLine(lineId);
    if (skipped) toast(t("receiving.toast.skipped"));
  };
  return { skipAsk, setSkipAsk, handleSkipLine };
}

export default function WmsReceivingView({
  documentId,
  onClose,
  onRequestApproval,
}: Props) {
  const { t } = useTranslation("warehouse");
  const queryClient = useQueryClient();
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
    refreshPlans,
    confirmShortReceive: confirmShort,
    skipLine,
    finishWithoutRest,
    undoLine,
    completeSession,
    cancelSession,
    requestShortReceive,
    cancelShortReceive,
    reset,
  } = useWmsReceiving(documentId);
  const isPhone = useMediaQuery(PHONE_QUERY);

  const sessionError =
    error ?? (errorContext ? failureSentence(t, errorContext) : null);

  // the document page reads its data through React Query and does not
  // refetch when a receiving session ends — invalidate the document detail so
  // "Done 0 / Planned 1" refreshes to the received counts without a reload.
  const invalidateDocument = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.documents.detail(documentId),
    });
  };

  // When the start was refused because someone else's session holds the
  // document, the dialog offers two ways out: take the session over with the
  // scans already made, or put the holder's scans back. Either way the
  // reader's own session starts next. Without them the refusal is a dead
  // end — the document waits for a holder who walked away.
  const handleHeldSession = async (act: () => Promise<unknown>) => {
    const failure = await act();
    if (failure !== null) {
      toast.error(extractApiError(failure, t("receiving.error.start_failed")));
      return;
    }
    invalidateDocument();
    startSession();
  };

  const shelves = useFloorShelves(documentId, state.lines, () => {
    invalidateDocument();
    void refreshPlans();
  });

  // Guard against React StrictMode double-invoking the mount effect in dev:
  // a second start would fail with "session already exists" (structured error).
  const startedRef = useRef(false);
  useEffect(() => {
    if (state.phase === "idle" && !startedRef.current) {
      startedRef.current = true;
      startSession();
    }
  }, [state.phase, startSession]);

  // A scan the server answered with "needs_lot_expiry", waiting for the lot
  // and date the worker reads off the pack. It is sent again with them.
  // A tap on "Receive full amount" or the short-receive sheet is asked the
  // same way, and sends its own call again, which is why the ask holds the
  // resend rather than a barcode.
  const [lotExpiryAsk, setLotExpiryAsk] = useState<LotExpiryAsk | null>(null);

  // A count past the over-receipt tolerance, asked of a worker who may
  // receive over it. The same call goes again with the answer.
  const surplus = useSurplusQuestion();

  const shortSheetLine = shortSheetLineFor(state, lotExpiryAsk);
  const heldFromCard = useHeldFromCard(requestShortReceive, shortSheetLine);
  const handleScan = async (
    barcode: string,
    quantity: number,
    tracking?: { batch_number?: string; expiry_date?: string },
    identify = false,
    confirmSurplus = false,
  ): Promise<WmsReceiveScanResult | null> => {
    const result = await scan(
      barcode,
      quantity,
      tracking,
      identify,
      confirmSurplus,
    );
    if (result?.status === "rejected") invalidateDocument();
    const again = () => handleScan(barcode, quantity, tracking, identify, true);
    if (surplus.askIf(result, again)) return result;
    if (result?.status === "needs_lot_expiry") {
      setLotExpiryAsk({
        productName: result.product_name,
        resend: (asked) =>
          void handleScan(barcode, quantity, asked, identify, confirmSurplus),
      });
      // The product is known already: the phone shows its card while the
      // question about its lot is open.
      return result;
    }
    setLotExpiryAsk(null);
    // On a phone the refusal is said beside the scan field and stays there;
    // a toast over the title is gone before the worker looks up from the
    // viewfinder.
    if (isPhone && receivingRefusal(t, result)) return result;
    announceScanResult(t, result, barcode);
    return result;
  };

  const handleUndoLine = async (line: WmsReceiveLine) => {
    const undone = await undoLine(line.id);
    // Only when the server undid it: a refused undo answers with its own
    // sentence, and the white toast used to fire beside the red refusal.
    if (undone)
      toast(t("receiving.toast.undo", { product: line.product_name ?? "" }));
  };

  const handleShortReceiveConfirm = async (
    lineId: string,
    qty: number,
    code: string,
    reason?: string,
    replaceScans?: boolean,
    heldQty = 0,
    tracking?: { batch_number?: string; expiry_date?: string },
    confirmSurplus = false,
  ): Promise<void> => {
    const result = await confirmShort(
      lineId,
      qty,
      code,
      reason,
      replaceScans,
      heldQty,
      tracking,
      confirmSurplus,
    );
    const again = (asked: typeof tracking, confirmed: boolean) =>
      handleShortReceiveConfirm(
        lineId,
        qty,
        code,
        reason,
        replaceScans,
        heldQty,
        asked,
        confirmed,
      );
    if (!result || surplus.askIf(result, () => again(tracking, true))) return;
    if (result.status === "needs_lot_expiry") {
      setLotExpiryAsk({
        productName: result.product_name,
        resend: (asked) => void again(asked, confirmSurplus),
      });
      return;
    }
    setLotExpiryAsk(null);
    announceShortReceive(t, result);
  };

  // The whole line in one tap: the number is the document's own expectation,
  // and no discrepancy code travels with it — a full receive carries none.
  const handleFullReceive = (line: WmsReceiveLine) => {
    void handleShortReceiveConfirm(line.id, Number(line.expected_quantity), "");
  };

  const { skipAsk, setSkipAsk, handleSkipLine } = useSkipAsk(skipLine);

  const handleComplete = async () => {
    const closed = await completeSession();
    invalidateDocument();
    // Only when the server closed it. The refusal it answers with — "Cannot
    // complete: 1 lines still pending" — used to arrive under a green
    // "completed", and the reader had two contradictory sentences and no way
    // to tell which one was true.
    if (closed) toast.success(t("receiving.toast.completed"));
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
    // Closing the sheet is not a decision to put anything back: what was
    // received stays on the session, and the next start hands it back —
    // the resume the browser's back arrow always had. Putting things back
    // is the named Cancel button's job.
    invalidateDocument();
    reset();
    onClose();
  };

  if (state.phase === "idle") {
    // mirror of the picking view — surface start failures
    // (e.g. 409 APPROVAL_REQUIRED) instead of a blank view.
    // `errorStatus`, not `error`: the message is what the API said and a 500
    // says nothing worth showing, so it is legitimately absent. Branching on
    // it would put a blank view back exactly where the failure is hardest to
    // explain.
    if (errorStatus !== null) {
      return (
        <ReceivingStartFailure
          error={error}
          errorCode={errorCode}
          errorStatus={errorStatus}
          holderName={heldSession?.holderName ?? null}
          onTakeOver={() => handleHeldSession(takeOverHeldSession)}
          onRelease={() => handleHeldSession(releaseHeldSession)}
          onRetry={startSession}
          onRequestApproval={onRequestApproval}
          onClose={() => onClose()}
        />
      );
    }
    return isLoading ? (
      <div className="flex justify-center py-10">
        <LoadingSpinner />
      </div>
    ) : null;
  }

  // The phone posts the completion by itself, and the server refuses it while
  // a skipped line has no answer: that case gets the summary, below.
  const phoneDone = isPhone && !state.lines.some((l) => l.status === "skipped");
  if (state.phase === "completed" && state.session && phoneDone) {
    return (
      <WmsReceivingPhoneDone
        documentId={documentId}
        lines={state.lines}
        // The document is completed by this screen already; closing it
        // books nothing more.
        onClose={() => {
          reset();
          onClose();
        }}
      />
    );
  }

  if (state.phase === "completed" && state.session) {
    return (
      <WmsReceivingSummary
        lines={state.lines}
        onUndoSkip={(line) => void handleUndoLine(line)}
        onAnswerSkip={(line, code) => void confirmShort(line.id, 0, code)}
        isLoading={isLoading}
        error={sessionError}
        onClose={() => {
          // Closing the summary is what completes the document and books
          // the stock, as it is in picking. The last scan used to book on
          // its own, with nothing to look at first.
          reset();
          onClose(true);
        }}
        // Refresh the document the moment the summary appears, not when it is
        // dismissed: the summary said "received" over a document still
        // reading "Planned 1 / Done 0" behind it.
        onShown={invalidateDocument}
      />
    );
  }

  if (state.phase === "cancelled") return null;

  return (
    <div className="relative">
      {/* Without the shelves a worker cannot re-aim a line, and an empty list
          would read as "this warehouse has none". */}
      {shelves.tree.isError && (
        <div className="px-4 py-2">
          <InlineQueryError
            error={shelves.tree.error}
            onRetry={() => void shelves.tree.refetch()}
          />
        </div>
      )}
      {isPhone ? (
        <WmsReceivingPhone
          documentId={documentId}
          session={state.session!}
          lines={state.lines}
          isLoading={isLoading}
          error={sessionError}
          locations={shelves.choices}
          targetChangePending={shelves.pending}
          onTargetChange={shelves.aim}
          onScan={(barcode) => handleScan(barcode, 1, undefined, true)}
          // The count on the card is the line's total, so a number below
          // what was scanned of it replaces the scans: the worker set it.
          onConfirm={(line, qty) =>
            handleShortReceiveConfirm(
              line.id,
              qty,
              "",
              undefined,
              qty < line.received_quantity,
            )
          }
          onFinishWithoutRest={() => void finishWithoutRest()}
          onReportHeld={heldFromCard.open}
          onComplete={handleComplete}
          onClose={handleClose}
        />
      ) : (
        <WmsReceivingActive
          session={state.session!}
          lines={state.lines}
          isLoading={isLoading}
          error={sessionError}
          targetChangePending={shelves.pending}
          onTargetChange={shelves.aim}
          onScan={handleScan}
          onUndoLine={handleUndoLine}
          onFullReceive={handleFullReceive}
          onShortReceive={(line) => requestShortReceive(line.id)}
          onSkipLine={setSkipAsk}
          onComplete={handleComplete}
          onCancel={handleCancel}
          onClose={handleClose}
        />
      )}

      {lotExpiryAsk && (
        <LotExpiryAskDialog
          ask={lotExpiryAsk}
          isLoading={isLoading}
          serverError={sessionError}
          onCancel={() => setLotExpiryAsk(null)}
        />
      )}

      {surplus.dialog}

      <WmsSkipConfirm
        line={skipAsk}
        title={t("receiving.skip_confirm_title")}
        message={(product) => t("receiving.skip_confirm_message", { product })}
        confirmLabel={t("receiving.line.skipAction")}
        onConfirm={(line) => {
          setSkipAsk(null);
          void handleSkipLine(line.id);
        }}
        onCancel={() => setSkipAsk(null)}
      />

      {shortSheetLine && (
        <WmsShortReceiveDialog
          line={shortSheetLine}
          initialQuantity={heldFromCard.quantity}
          isLoading={isLoading}
          serverError={sessionError}
          onConfirm={handleShortReceiveConfirm}
          onCancel={cancelShortReceive}
        />
      )}
    </div>
  );
}
