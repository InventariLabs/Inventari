import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { scanLookupError } from "@/module-sdk";
import { documentsApi } from "../api/documents";
import type { WmsPickLine, WmsPickSession } from "../api/documents";
import { awaitsDestination } from "../components/ShelfConfirmation";
import { useWmsSession } from "./useWmsSession";
import type { WmsSessionTransport } from "./useWmsSession";

type WmsPickingPhase =
  "idle" | "active" | "short_pick" | "completed" | "cancelled";

/**
 * Which action failed last. The hook carries only what the API said — for
 * a 5xx that is nothing — and names the action so the view can speak the
 * namespace's sentence for it. An English literal here is one the reader
 * would meet on a Polish screen.
 */
export type WmsPickingFailureContext =
  "scan" | "short_pick" | "skip" | "undo" | "complete" | "cancel";

interface WmsPickingState {
  phase: WmsPickingPhase;
  session: WmsPickSession | null;
  lines: WmsPickLine[];
  shortPickLine: WmsPickLine | null;
}

const TRANSPORT: WmsSessionTransport<WmsPickSession, WmsPickLine> = {
  start: (documentId) => documentsApi.startWmsPicking(documentId),
  skip: (documentId, sessionId, lineId) =>
    documentsApi.wmsPickingSkip(documentId, sessionId, lineId),
  undo: (documentId, sessionId, lineId) =>
    documentsApi.wmsPickingUndo(documentId, sessionId, lineId),
  complete: (documentId, sessionId) =>
    documentsApi.wmsPickingComplete(documentId, sessionId),
  cancel: (documentId, sessionId) =>
    documentsApi.wmsPickingCancel(documentId, sessionId),
  pause: (documentId, sessionId) =>
    documentsApi.wmsPickingPause(documentId, sessionId),
  release: (documentId, sessionId) =>
    documentsApi.wmsPickingRelease(documentId, sessionId),
  takeOver: (documentId, sessionId) =>
    documentsApi.wmsPickingTakeOver(documentId, sessionId),
  linesOf: (session) => session.lines,
  clearedLine: (line, status) => ({ ...line, status, picked_quantity: 0 }),
  doneStatus: "picked",
  awaitsMore: awaitsDestination,
};

/**
 * `documentIds` starts one session over several dispatches. The session is
 * reached through any of its documents afterwards, so `documentId` (the
 * first of them) keeps addressing every later call.
 */
export function useWmsPicking(documentId: string, documentIds?: string[]) {
  const { t } = useTranslation();
  // Keyed on the joined ids: a caller's array is a new object on every render.
  const idsKey = documentIds?.join(",") ?? "";
  const transport = useMemo(
    () =>
      !idsKey.includes(",")
        ? TRANSPORT
        : {
            ...TRANSPORT,
            start: () =>
              documentsApi.startWmsPickingDocuments(idsKey.split(",")),
          },
    [idsKey],
  );
  const session = useWmsSession<WmsPickSession, WmsPickLine>(
    documentId,
    transport,
  );
  const { state, setState, setIsLoading, setError, setErrorContext } = session;

  /**
   * The state after a scan the server accepted: the line carries its new
   * quantity, and the session closes when the server says so. Shared by
   * both scan paths — barcode and quant — which answered the same result
   * the same way, twice.
   */
  const scanned = useCallback(
    (result: {
      line_id: string | null;
      picked_quantity: number;
      expected_quantity: number;
      lot_name?: string | null;
      expiry_date?: string | null;
      session_complete: boolean;
    }) => {
      setState((prev) => ({
        phase: result.session_complete ? "completed" : "active",
        session: prev.session,
        lines: prev.lines.map((ln) =>
          ln.id === result.line_id
            ? {
                ...ln,
                // a partial scan leaves the line open — the picker is
                // expected to come back with the rest of it.
                status:
                  result.picked_quantity >= result.expected_quantity
                    ? ("picked" as const)
                    : ("pending" as const),
                picked_quantity: result.picked_quantity,
                // a scan that named another batch moved the line to it
                lot_name: result.lot_name ?? ln.lot_name,
                expiry_date:
                  result.lot_name && result.lot_name !== ln.lot_name
                    ? (result.expiry_date ?? null)
                    : ln.expiry_date,
              }
            : ln,
        ),
        shortLine: null,
      }));
    },
    [setState],
  );

  // The shelf the server accepted (null once it refuses another), kept on the
  // session so every row can say whether its own shelf is the one the worker
  // stands at.
  const rememberShelf = useCallback(
    (shelfId: string | null | undefined) => {
      setState((prev) =>
        prev.session
          ? {
              ...prev,
              session: { ...prev.session, confirmed_shelf_id: shelfId ?? null },
            }
          : prev,
      );
    },
    [setState],
  );

  // The scan is where the two sessions genuinely differ: picking's answers
  // with the line it picked. So it is written here rather than
  // parameterised into the shared machine.
  const scan = useCallback(
    async (barcode: string, quantity = 1, lotName?: string) => {
      if (state.phase !== "active" || !state.session) return null;
      setIsLoading(true);
      setError(null);
      setErrorContext(null);
      try {
        const result = await documentsApi.wmsPickingScan(
          documentId,
          state.session.id,
          { barcode, quantity, lot_name: lotName },
        );
        if (result.status === "picked") scanned(result);
        if (result.status === "shelf_confirmed") {
          // The destination label of a transfer ends the session.
          if (result.session_complete) {
            setState((prev) => ({
              ...prev,
              phase: "completed",
              shortLine: null,
            }));
          } else {
            rememberShelf(result.shelf_id);
          }
        }
        // A refused label withdraws the confirmation, as it does on the server.
        if (result.status === "wrong_shelf") rememberShelf(null);
        return result;
      } catch (e: unknown) {
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
      scanned,
      rememberShelf,
      setState,
      setIsLoading,
      setError,
      setErrorContext,
      t,
    ],
  );

  const confirmShortPick = useCallback(
    async (
      lineId: string,
      pickedQty: number,
      code?: string,
      reason?: string,
      replaceScans = false,
    ) => {
      return session.run("shortfall", async (live) => {
        const result = await documentsApi.wmsPickingShortPick(
          documentId,
          live.id,
          lineId,
          pickedQty,
          code,
          reason,
          replaceScans,
        );
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
        // A full pick is a full pick. This dialog is not only for shortages —
        // a product with no barcode can be picked no other way — and the
        // server derives the line status from the quantities either way.
        // Hardcoding "short" here reported a shortage that never happened.
        const line = state.lines.find((ln) => ln.id === lineId);
        const isFullPick =
          line !== undefined && pickedQty >= line.expected_quantity;
        const lineStatus: WmsPickLine["status"] = isFullPick
          ? "picked"
          : "short";
        setState({
          phase: result.session_complete ? "completed" : "active",
          session: live,
          lines: state.lines.map((ln) =>
            ln.id === lineId
              ? { ...ln, status: lineStatus, picked_quantity: pickedQty }
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

  const pickingState: WmsPickingState = {
    phase: state.phase === "shortfall" ? "short_pick" : state.phase,
    session: state.session,
    lines: state.lines,
    shortPickLine: state.shortLine,
  };

  return {
    state: pickingState,
    isLoading: session.isLoading,
    error: session.error,
    errorCode: session.errorCode,
    errorStatus: session.errorStatus,
    startError: session.startError,
    errorContext: (session.errorContext === "shortfall"
      ? "short_pick"
      : session.errorContext) as WmsPickingFailureContext | null,
    pickedCount: session.doneCount,
    pendingCount: session.pendingCount,
    totalCount: session.totalCount,
    startSession: session.startSession,
    scan,
    confirmShortPick,
    skipLine: session.skipLine,
    undoLine: session.undoLine,
    completeSession: session.completeSession,
    cancelSession: session.cancelSession,
    heldSession: session.heldSession,
    releaseHeldSession: session.releaseHeldSession,
    takeOverHeldSession: session.takeOverHeldSession,
    requestShortPick: session.requestShortfall,
    cancelShortPick: session.cancelShortfall,
    reset: session.reset,
  };
}
