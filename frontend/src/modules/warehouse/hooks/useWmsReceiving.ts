import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import { scanLookupError } from "@/module-sdk";
import { documentsReceivingApi } from "../api/documents_receiving";
import type {
  WmsReceiveLine,
  WmsReceiveScanResult,
  WmsReceiveSession,
} from "../api/documents_receiving";
import { OPEN_SESSION_STATUSES, useWmsSession } from "./useWmsSession";
import type { WmsSessionTransport } from "./useWmsSession";

type WmsReceivingPhase =
  "idle" | "active" | "short_receive" | "completed" | "cancelled";

/**
 * Which action failed last. The hook carries only what the API said — for
 * a 5xx that is nothing — and names the action so the view can speak the
 * namespace's sentence for it. An English literal here is one the reader
 * would meet on a Polish screen.
 */
export type WmsReceivingFailureContext =
  "scan" | "short_receive" | "skip" | "undo" | "complete" | "cancel";

interface WmsReceivingState {
  phase: WmsReceivingPhase;
  session: WmsReceiveSession | null;
  lines: WmsReceiveLine[];
  shortReceiveLine: WmsReceiveLine | null;
}

/**
 * A count the server asked about rather than refused, as the answer the
 * view reads. Past the over-receipt tolerance a worker who may receive over
 * it is answered 409 SURPLUS_NEEDS_CONFIRMATION with a sentence naming the
 * surplus: nothing was recorded, and the view asks the question and sends
 * the same count again with the answer — the way it asks for a lot and
 * expiry. Null for every other failure.
 */
function surplusQuestionOf(error: unknown): WmsReceiveScanResult | null {
  if (extractApiErrorCode(error) !== "SURPLUS_NEEDS_CONFIRMATION") return null;
  return {
    status: "needs_surplus_confirmation",
    message: extractApiError(error, ""),
    line_id: null,
    product_name: null,
    uom_symbol: null,
    received_quantity: 0,
    expected_quantity: 0,
    session_complete: false,
  };
}

const TRANSPORT: WmsSessionTransport<WmsReceiveSession, WmsReceiveLine> = {
  start: (documentId) => documentsReceivingApi.startWmsReceiving(documentId),
  skip: (documentId, sessionId, lineId) =>
    documentsReceivingApi.wmsReceivingSkip(documentId, sessionId, lineId),
  undo: (documentId, sessionId, lineId) =>
    documentsReceivingApi.wmsReceivingUndo(documentId, sessionId, lineId),
  complete: (documentId, sessionId) =>
    documentsReceivingApi.wmsReceivingComplete(documentId, sessionId),
  cancel: (documentId, sessionId) =>
    documentsReceivingApi.wmsReceivingCancel(documentId, sessionId),
  pause: (documentId, sessionId) =>
    documentsReceivingApi.wmsReceivingPause(documentId, sessionId),
  release: (documentId, sessionId) =>
    documentsReceivingApi.wmsReceivingRelease(documentId, sessionId),
  takeOver: (documentId, sessionId) =>
    documentsReceivingApi.wmsReceivingTakeOver(documentId, sessionId),
  linesOf: (session) => session.lines,
  // Undo leaves nothing set aside either: the server clears the quarantined
  // part and its reason with the count.
  clearedLine: (line, status) => ({
    ...line,
    status,
    received_quantity: 0,
    held_quantity: 0,
    discrepancy_code: null,
  }),
  doneStatus: "received",
};

export function useWmsReceiving(documentId: string) {
  const { t } = useTranslation();
  const session = useWmsSession<WmsReceiveSession, WmsReceiveLine>(
    documentId,
    TRANSPORT,
  );
  const { state, setState, setIsLoading, setError, setErrorContext } = session;

  // The scan is where the two sessions genuinely differ: receiving's
  // carries the quantity that arrived, and reads it back. So it is written
  // here rather than parameterised into the shared machine.
  const scan = useCallback(
    async (
      barcode: string,
      quantity: number,
      tracking?: { batch_number?: string; expiry_date?: string },
      // The phone's scan brings a card up and counts nothing: the count is
      // confirmed on the card. The answer is "identified", which leaves the
      // rows as they are.
      identify = false,
      // The worker said yes to the surplus a scan was asked about.
      confirmSurplus = false,
    ) => {
      if (state.phase !== "active" || !state.session) return null;
      setIsLoading(true);
      setError(null);
      setErrorContext(null);
      try {
        const result = await documentsReceivingApi.wmsReceivingScan(
          documentId,
          state.session.id,
          { barcode, quantity, ...tracking, ...(identify && { identify }) },
          confirmSurplus,
        );

        if (
          result.status === "shelf_confirmed" ||
          result.status === "wrong_shelf"
        ) {
          // The shelf the server accepted — none once it refuses another —
          // kept on the session so every row can say whether its own shelf is
          // the one the worker stands at.
          setState((prev) =>
            prev.session
              ? {
                  ...prev,
                  session: {
                    ...prev.session,
                    confirmed_shelf_id:
                      result.status === "shelf_confirmed"
                        ? (result.shelf_id ?? null)
                        : null,
                  },
                }
              : prev,
          );
        }

        if (result.status === "received") {
          // "received" is what the server answers for every accepted scan,
          // including a partial one — 5 of 12.5 comes back with the same word
          // as 12.5 of 12.5. Reading it as the line's status marked a
          // half-delivered line complete: the scan field disappeared, and with
          // it "Short receive" and "Skip", in the one situation they exist for.
          // The quantities are the only honest source, and the short-receive
          // branch below has always read them.
          setState((prev) => {
            const line = prev.lines.find((ln) => ln.id === result.line_id);
            const isFullReceive =
              line !== undefined &&
              result.received_quantity >= line.expected_quantity;
            return {
              phase: result.session_complete ? "completed" : "active",
              session: prev.session,
              lines: prev.lines.map((ln) =>
                ln.id === result.line_id
                  ? {
                      ...ln,
                      status: (isFullReceive
                        ? "received"
                        : "pending") as WmsReceiveLine["status"],
                      received_quantity: result.received_quantity,
                    }
                  : ln,
              ),
              shortLine: null,
            };
          });
        }

        return result;
      } catch (e: unknown) {
        const question = surplusQuestionOf(e);
        if (question) return question;
        setErrorContext("scan");
        // Past the per-minute ceiling the API's own "try again later" says
        // nothing a scanner can act on; the scan screens share one sentence.
        setError(scanLookupError(e, "", t) || null);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [
      state.phase,
      state.session,
      documentId,
      setState,
      setIsLoading,
      setError,
      setErrorContext,
      t,
    ],
  );

  const confirmShortReceive = useCallback(
    async (
      lineId: string,
      receivedQty: number,
      code?: string,
      reason?: string,
      replaceScans = false,
      heldQuantity = 0,
      tracking?: { batch_number?: string; expiry_date?: string },
      confirmSurplus = false,
    ): Promise<WmsReceiveScanResult | null> => {
      return session.run("shortfall", async (live) => {
        const result = await documentsReceivingApi
          .wmsReceivingShortReceive(
            documentId,
            live.id,
            lineId,
            receivedQty,
            code,
            reason,
            replaceScans,
            heldQuantity,
            tracking,
            confirmSurplus,
          )
          .catch((e: unknown) => {
            const question = surplusQuestionOf(e);
            if (question) return question;
            throw e;
          });
        // A dated product asks for its lot and expiry first, as its scan
        // does, and a surplus past the tolerance asks its holder: nothing
        // was recorded, so the rows and the dialog stay.
        if (
          result.status === "needs_lot_expiry" ||
          result.status === "needs_surplus_confirmation"
        )
          return result;
        // The server refused the quantity because the location was not
        // scanned: nothing was recorded, so the rows stay as they are.
        if (result.status === "shelf_required") {
          setState({
            phase: "active",
            session: live,
            lines: state.lines,
            shortLine: null,
          });
          return result;
        }
        // a full receive is a full receive — the backend answers
        // "short_receive_confirmed" for every quantity this route accepts,
        // so derive the line status from the quantities instead of
        // hardcoding "short".
        const line = state.lines.find((ln) => ln.id === lineId);
        const isFullReceive =
          line !== undefined && receivedQty >= line.expected_quantity;
        const lineStatus: WmsReceiveLine["status"] = isFullReceive
          ? "received"
          : "short";
        setState({
          phase: result.session_complete ? "completed" : "active",
          session: live,
          lines: state.lines.map((ln) =>
            ln.id === lineId
              ? {
                  ...ln,
                  status: lineStatus,
                  received_quantity: receivedQty,
                  held_quantity: heldQuantity,
                  // The reason travels with the quantity it explains.
                  discrepancy_code: (heldQuantity > 0
                    ? (code ?? null)
                    : null) as WmsReceiveLine["discrepancy_code"],
                }
              : ln,
          ),
          shortLine: null,
        });
        // Tell the caller what actually happened so the toast is honest.
        return { ...result, status: lineStatus };
      });
    },
    [session, state.lines, documentId, setState],
  );

  /**
   * Read the session again, keeping the rows the worker has since resolved.
   *
   * A row's planned shelf is computed from the document's lines, not stored
   * on the session's — so naming a shelf changes the plan without touching
   * anything this state machine holds, and the rows would keep showing the
   * old address until the screen was reopened. Statuses and counts are
   * carried over rather than taken from the response, because for a row
   * taken a moment ago the local machine is ahead of the server: the phone
   * names a shelf and confirms the count at once, and a read answered
   * before the count put the line back to nothing received.
   */
  const refreshPlans = useCallback(async () => {
    if (!state.session) return;
    const sessionId = state.session.id;
    try {
      const live = await documentsReceivingApi.getWmsReceivingSession(
        documentId,
        sessionId,
      );
      setState((prev) => ({
        ...prev,
        lines: live.lines.map((fresh) => {
          const known = prev.lines.find((ln) => ln.id === fresh.id);
          return known
            ? {
                ...fresh,
                status: known.status,
                received_quantity: known.received_quantity,
              }
            : fresh;
        }),
      }));
    } catch {
      // A failed refresh leaves the previous plan on screen. That is the
      // honest fallback here: the picker still shows what the worker chose,
      // and the next action reads the session again anyway.
    }
  }, [documentId, state.session, setState]);

  /**
   * "The rest did not come": close every open line with what arrived of it
   * and read the session back as the server stored it.
   *
   * Every line is answered as a short receive, a line nothing of which
   * arrived with a count of nothing. The skip it would be otherwise records
   * no reason, which is for the summary to ask, and this button is the
   * answer already: the missing quantity stays expected on the order. The
   * rows are taken from the server afterwards, also after a refusal halfway,
   * because the lines closed before it are closed whatever the screen
   * assumed.
   */
  const finishWithoutRest = useCallback(async (): Promise<boolean> => {
    const done = await session.run("skip", async (live) => {
      try {
        for (const line of state.lines) {
          if (line.status !== "pending") continue;
          await documentsReceivingApi.wmsReceivingShortReceive(
            documentId,
            live.id,
            line.id,
            line.received_quantity,
          );
        }
      } finally {
        await documentsReceivingApi
          .getWmsReceivingSession(documentId, live.id)
          .then((stored) =>
            setState({
              phase: OPEN_SESSION_STATUSES.has(stored.status)
                ? "active"
                : "completed",
              session: stored,
              lines: stored.lines,
              shortLine: null,
            }),
          )
          // An unreadable session leaves the rows as they were; the next
          // action reads it again.
          .catch(() => undefined);
      }
      return true;
    });
    return done === true;
  }, [session, state.lines, documentId, setState]);

  const receivingState: WmsReceivingState = {
    phase: state.phase === "shortfall" ? "short_receive" : state.phase,
    session: state.session,
    lines: state.lines,
    shortReceiveLine: state.shortLine,
  };

  return {
    state: receivingState,
    isLoading: session.isLoading,
    error: session.error,
    errorCode: session.errorCode,
    errorStatus: session.errorStatus,
    startError: session.startError,
    errorContext: (session.errorContext === "shortfall"
      ? "short_receive"
      : session.errorContext) as WmsReceivingFailureContext | null,
    receivedCount: session.doneCount,
    pendingCount: session.pendingCount,
    totalCount: session.totalCount,
    startSession: session.startSession,
    scan,
    refreshPlans,
    confirmShortReceive,
    skipLine: session.skipLine,
    finishWithoutRest,
    undoLine: session.undoLine,
    completeSession: session.completeSession,
    cancelSession: session.cancelSession,
    heldSession: session.heldSession,
    releaseHeldSession: session.releaseHeldSession,
    takeOverHeldSession: session.takeOverHeldSession,
    requestShortReceive: session.requestShortfall,
    cancelShortReceive: session.cancelShortfall,
    reset: session.reset,
  };
}
