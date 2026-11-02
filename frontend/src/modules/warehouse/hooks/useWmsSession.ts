import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import {
  apiErrorStatus,
  extractApiError,
  extractApiErrorCode,
  extractApiErrorField,
} from "@/lib/errors";
import { useLeftOpenNotice } from "./useLeftOpenNotice";

/**
 * The part of a WMS session that picking and receiving do the same way.
 *
 * The two hooks were written as siblings — the receiving one still says
 * "Mirrors useWmsPicking" — and the sequence around every action is
 * identical: guard on a live session, raise the loading flag, clear the
 * last error, call, record which action failed, lower the flag. Seven of
 * the nine actions differ only in which endpoint they call.
 *
 * They had already drifted twice, and both times the repair landed on one
 * side: `complete` learned to report the server's refusal in receiving
 * first, and deriving a line's status from the quantities rather than from
 * the word the server answers was fixed in receiving and later in picking.
 *
 * What stays in each hook is what genuinely differs: the scan — picking's
 * carries no quantity and has a second form by quant, receiving's carries
 * one — and the shortfall confirmation. Those read the result differently,
 * and hiding that behind a parameter would make the difference harder to
 * see rather than smaller.
 */

const IN_PROGRESS = ["active", "shortfall"] as const;

/** Neutral phase names. Each hook maps `shortfall` onto its own word. */
export type WmsSessionPhase =
  "idle" | "active" | "shortfall" | "completed" | "cancelled";

/**
 * Which action failed last. The hook carries only what the API said — for
 * a 5xx that is nothing — and names the action so the view can speak the
 * namespace's sentence for it. An English literal here is one the reader
 * would meet on a Polish screen.
 */
export type WmsSessionFailureContext =
  "scan" | "shortfall" | "skip" | "undo" | "complete" | "cancel";

/** The least a line has to be for the shared actions to work on it. */
export interface WmsSessionLine {
  id: string;
  status: string;
  expected_quantity: number;
}

export interface WmsSessionState<TSession, TLine> {
  phase: WmsSessionPhase;
  session: TSession | null;
  lines: TLine[];
  shortLine: TLine | null;
}

/** The least a session has to be for the shared actions to address it. */
export interface WmsSessionIdentity {
  id: string;
  status: string;
}

/** The statuses a session is still being scanned in. */
export const OPEN_SESSION_STATUSES = new Set(["active", "paused"]);

/** The endpoints and the two line edits that differ only in field name. */
export interface WmsSessionTransport<TSession, TLine> {
  start(documentId: string): Promise<TSession>;
  skip(documentId: string, sessionId: string, lineId: string): Promise<unknown>;
  undo(documentId: string, sessionId: string, lineId: string): Promise<unknown>;
  complete(documentId: string, sessionId: string): Promise<unknown>;
  cancel(documentId: string, sessionId: string): Promise<unknown>;
  /** Lets go of the caller's own session, keeping its scans. */
  pause(documentId: string, sessionId: string): Promise<unknown>;
  /** Puts a session someone else holds back, discarding its scans. */
  release(documentId: string, sessionId: string): Promise<unknown>;
  /** Moves an open session, with its scans, to the caller. */
  takeOver(documentId: string, sessionId: string): Promise<unknown>;
  linesOf(session: TSession): TLine[];
  /** The line with nothing counted against it yet, skipped or back to pending. */
  clearedLine(line: TLine, status: "pending" | "skipped"): TLine;
  /** What this side calls a line that is fully done: picked, or received. */
  doneStatus: string;
  /** Whether the session goes on after its last line is answered. */
  awaitsMore?(session: TSession, lines: TLine[]): boolean;
}

export function useWmsSession<
  TSession extends WmsSessionIdentity,
  TLine extends WmsSessionLine,
>(documentId: string, transport: WmsSessionTransport<TSession, TLine>) {
  const [state, setState] = useState<WmsSessionState<TSession, TLine>>({
    phase: "idle",
    session: null,
    lines: [],
    shortLine: null,
  });
  // Whichever screen shows the session, going away with it open says the
  // scans are kept; the cancel below is the exit that does not.
  // Leaving pauses the session: its scans stay, and the document is free to
  // be completed or continued by anyone. Not awaited — the screen is
  // already gone, and a session left unpaused is released by its idle time.
  // The id outlives `reset`, which the sheet's own close calls before the
  // screen goes away.
  // The documents are read again once the pause has landed: the close's own
  // refresh runs before it, and the notice read the session as still active
  // — no "complete with the scans" — until the page was reloaded. The To do
  // list is among them: it shows who holds a document, and "Resume" instead
  // of "Pick", only after this refresh.
  const queryClient = useQueryClient();
  const lastSessionId = useRef<string | null>(null);
  useEffect(() => {
    if (state.session) lastSessionId.current = state.session.id;
  }, [state.session]);
  const pauseOnLeave = useCallback(() => {
    const sessionId = lastSessionId.current;
    if (!sessionId) return;
    void transport
      .pause(documentId, sessionId)
      .then(() =>
        queryClient.invalidateQueries({ queryKey: queryKeys.documents.all }),
      )
      .catch(() => {});
  }, [documentId, transport, queryClient]);
  const disarmLeftOpenNotice = useLeftOpenNotice(
    state.phase,
    IN_PROGRESS,
    pauseOnLeave,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  // A refusal and a malfunction both land in `error` as a sentence.
  // Only the status tells them apart, and only one of the two is
  // worth offering a retry for.
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [errorContext, setErrorContext] =
    useState<WmsSessionFailureContext | null>(null);
  // The raw start failure, kept beside its sentence: some refusals carry
  // machine-readable context in the detail envelope (the session id a held
  // document can be released with) that the sentence alone leaves behind.
  const [startError, setStartError] = useState<unknown>(null);

  /**
   * Run one action against the live session and report what happened.
   *
   * Returns `null` when there is no session or the call failed — the two
   * cases every caller already treated the same. On failure it records the
   * action, and the sentence the API sent: `extractApiError` hands back a
   * business rule already translated for a 4xx, and nothing for a 5xx, so
   * the null is deliberate and the view supplies the words.
   */
  const run = useCallback(
    async <T>(
      context: WmsSessionFailureContext,
      action: (session: TSession) => Promise<T>,
    ): Promise<T | null> => {
      if (!state.session) return null;
      setIsLoading(true);
      setError(null);
      setErrorContext(null);
      try {
        return await action(state.session);
      } catch (e: unknown) {
        setErrorContext(context);
        setError(extractApiError(e, "") || null);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [state.session],
  );

  const startSession = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setErrorCode(null);
    setErrorStatus(null);
    setErrorContext(null);
    setStartError(null);
    try {
      const session = await transport.start(documentId);
      // Start hands back a session that already finished when its summary
      // was left without completing the document: the sheet opens on that
      // summary, whose close completes it, not on lines to scan again.
      setState({
        phase: OPEN_SESSION_STATUSES.has(session.status)
          ? "active"
          : "completed",
        session,
        lines: transport.linesOf(session),
        shortLine: null,
      });
    } catch (e: unknown) {
      setStartError(e);
      setErrorCode(extractApiErrorCode(e));
      setErrorStatus(apiErrorStatus(e));
      setError(extractApiError(e, "") || null);
    } finally {
      setIsLoading(false);
    }
  }, [documentId, transport]);

  /**
   * Skip a line. Returns whether the server skipped it: a skip whose goods
   * a package already holds is refused, and the view announces only what
   * actually happened.
   */
  const skipLine = useCallback(
    async (lineId: string): Promise<boolean> => {
      const done = await run("skip", async (session) => {
        await transport.skip(documentId, session.id, lineId);
        const updated = state.lines.map((ln) =>
          ln.id === lineId ? transport.clearedLine(ln, "skipped") : ln,
        );
        const allResolved =
          updated.every((ln) => ln.status !== "pending") &&
          !transport.awaitsMore?.(session, updated);
        setState({
          phase: allResolved ? "completed" : "active",
          session,
          lines: updated,
          shortLine: null,
        });
        return true;
      });
      return done === true;
    },
    [run, state.lines, documentId, transport],
  );

  /**
   * Undo a line's recording. Returns whether the server undid it: a
   * refused undo — a package already holds the goods, the session was
   * closed from another tab — leaves the line counted, so the view must
   * not announce it as undone. Same answer as `completeSession` and
   * `cancelSession`: the caller tells success from refusal by the boolean,
   * never by absence of an error.
   */
  const undoLine = useCallback(
    async (lineId: string): Promise<boolean> => {
      const done = await run("undo", async (session) => {
        await transport.undo(documentId, session.id, lineId);
        setState({
          phase: "active",
          session,
          lines: state.lines.map((ln) =>
            ln.id === lineId ? transport.clearedLine(ln, "pending") : ln,
          ),
          shortLine: null,
        });
        return true;
      });
      return done === true;
    },
    [run, state.lines, documentId, transport],
  );

  /**
   * Whether the server closed the session. Saying nothing either way is how
   * a success toast came to fire next to the server's refusal — "Receiving
   * completed" and "Cannot complete: 1 lines still pending" at once.
   */
  const completeSession = useCallback(async (): Promise<boolean> => {
    const done = await run("complete", async (session) => {
      await transport.complete(documentId, session.id);
      setState((prev) => ({ ...prev, phase: "completed", shortLine: null }));
      return true;
    });
    return done === true;
  }, [run, documentId, transport]);

  /**
   * Whether the server cancelled the session. A refused cancel leaves it
   * open server-side, so the view has to keep the sheet — and the refusal
   * sentence — on screen instead of closing over it.
   */
  const cancelSession = useCallback(async (): Promise<boolean> => {
    const done = await run("cancel", async (session) => {
      await transport.cancel(documentId, session.id);
      disarmLeftOpenNotice();
      setState((prev) => ({ ...prev, phase: "cancelled", shortLine: null }));
      return true;
    });
    return done === true;
  }, [run, documentId, transport, disarmLeftOpenNotice]);

  const requestShortfall = useCallback(
    (lineId: string) => {
      const line = state.lines.find((ln) => ln.id === lineId);
      if (!line) return;
      setState({ ...state, phase: "shortfall", shortLine: line });
    },
    [state],
  );

  const cancelShortfall = useCallback(() => {
    setState({ ...state, phase: "active", shortLine: null });
  }, [state]);

  const reset = useCallback(() => {
    setState({ phase: "idle", session: null, lines: [], shortLine: null });
    setError(null);
    setErrorCode(null);
    setErrorStatus(null);
    setErrorContext(null);
    setStartError(null);
  }, []);

  // Both sides count a shortfall as resolved; only the word for a full
  // line differs, and the transport supplies it.
  const doneCount = state.lines.filter(
    (ln) => ln.status === transport.doneStatus || ln.status === "short",
  ).length;
  const pendingCount = state.lines.filter(
    (ln) => ln.status === "pending",
  ).length;

  /**
   * The held session behind a SESSION_HELD_BY_OTHER_USER refusal: the id
   * the release calls and the holder's name the dialog shows. Null for any
   * other failure, and for a refusal that arrived without the detail
   * envelope — nothing to release, nothing to name.
   */
  const heldSessionId =
    errorCode === "SESSION_HELD_BY_OTHER_USER" && startError !== null
      ? extractApiErrorField(startError, "held_session_id")
      : null;
  const heldSession = useMemo(
    () =>
      heldSessionId !== null && startError !== null
        ? {
            id: heldSessionId,
            holderName: extractApiErrorField(startError, "held_by") ?? "",
          }
        : null,
    [heldSessionId, startError],
  );

  /**
   * Put the held session back through the release door. Resolves null when
   * it worked, or with the error when it did not — the view quotes the
   * sentence, the hook does not speak.
   */
  const releaseHeldSession = useCallback(async (): Promise<unknown | null> => {
    if (heldSession === null) return null;
    try {
      await transport.release(documentId, heldSession.id);
      return null;
    } catch (e) {
      return e;
    }
  }, [heldSession, documentId, transport]);

  /**
   * Take the held session over, scans and all. Resolves null when it worked
   * (the caller then starts, and the start hands the session back as the
   * reader's own) or with the error when it did not.
   */
  const takeOverHeldSession = useCallback(async (): Promise<unknown | null> => {
    if (heldSession === null) return null;
    try {
      await transport.takeOver(documentId, heldSession.id);
      return null;
    } catch (e) {
      return e;
    }
  }, [heldSession, documentId, transport]);

  return {
    state,
    setState,
    run,
    isLoading,
    setIsLoading,
    error,
    setError,
    errorCode,
    errorStatus,
    errorContext,
    setErrorContext,
    startError,
    heldSession,
    releaseHeldSession,
    takeOverHeldSession,
    doneCount,
    pendingCount,
    totalCount: state.lines.length,
    startSession,
    skipLine,
    undoLine,
    completeSession,
    cancelSession,
    requestShortfall,
    cancelShortfall,
    reset,
  };
}
