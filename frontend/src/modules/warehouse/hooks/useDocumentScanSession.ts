import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { documentsReceivingApi } from "../api/documents_receiving";
import { documentsPickingApi } from "../api/documents_picking";

/** The two words the direction a session runs in is called by. */
export type ScanSessionKind = "receiving" | "picking";

/** The session's own facts — the fields the notice needs and no line. */
export interface DocumentScanSession {
  kind: ScanSessionKind;
  id: string;
  /**
   * `finished`: the session resolved every line and ended, but the document
   * it ran over was never completed — the summary that completes it was left
   * by the back arrow or a closed tab, and nothing is booked yet.
   */
  status: "active" | "paused" | "finished";
  started_at: string | null;
  assigned_to: string | null;
  /** Lines answered so far, and all of them — "2 of 3 picked". */
  doneLines: number;
  totalLines: number;
}

/** The statuses ``start`` hands back and every operation still accepts. */
const OPEN_STATUSES = new Set(["active", "paused"]);

/** How a session ends without being cancelled, in either direction. */
const FINISHED_STATUSES = new Set(["completed", "short_pick", "short_receive"]);

/**
 * The scanning session this document still has open — or, when none is, the
 * latest one, if it finished over a document nobody completed since.
 *
 * The two directions keep their own lists on the server, so both are read
 * and the session is taken from them: which direction a document takes is
 * the type's business, and asking both means the answer does not depend on
 * a second copy of that rule here. The picking list filters on nothing, so
 * a receiving session shows up in both and keeps its receiving name.
 *
 * A finished session is the server's own answer to the next start, and it
 * keeps the server's limit too: one that started before the document's
 * current confirmation (*confirmedAt*) belongs to an earlier version of the
 * document, and the next start counts afresh.
 *
 * The result nests under the document's own key, so the invalidation every
 * document write already fires (and the receiving view fires when a session
 * ends) refreshes this notice without a call of its own.
 */
export function useDocumentScanSession(
  documentId: string,
  options?: { enabled?: boolean; confirmedAt?: string | null },
) {
  const enabled = (options?.enabled ?? true) && Boolean(documentId);
  const confirmedAt = options?.confirmedAt ?? null;
  return useQuery({
    queryKey: queryKeys.documents.scanSession(documentId),
    queryFn: async (): Promise<DocumentScanSession | null> => {
      const [receiving, picking] = await Promise.all([
        documentsReceivingApi.listWmsReceivingSessions(documentId),
        documentsPickingApi.listWmsPickingSessions(documentId),
      ]);
      const inbound = new Set(receiving.map((s) => s.id));
      const sessions = [
        ...receiving.map((s) => ({
          kind: "receiving" as const,
          session: s,
          done: s.received_lines ?? 0,
        })),
        ...picking
          .filter((s) => !inbound.has(s.id))
          .map((s) => ({
            kind: "picking" as const,
            session: s,
            done: s.picked_lines ?? 0,
          })),
      ].sort(
        (a, b) =>
          Date.parse(b.session.started_at ?? "") -
          Date.parse(a.session.started_at ?? ""),
      );
      const open = sessions.find((s) => OPEN_STATUSES.has(s.session.status));
      const latest = sessions[0];
      const chosen =
        open ??
        (latest && FINISHED_STATUSES.has(latest.session.status)
          ? latest
          : undefined);
      if (!chosen) return null;
      return {
        kind: chosen.kind,
        id: chosen.session.id,
        status: open
          ? (chosen.session.status as DocumentScanSession["status"])
          : "finished",
        started_at: chosen.session.started_at ?? null,
        assigned_to: chosen.session.assigned_to ?? null,
        doneLines: chosen.done,
        totalLines: chosen.session.total_lines ?? 0,
      };
    },
    select: (session) =>
      session?.status === "finished" &&
      confirmedAt !== null &&
      Date.parse(session.started_at ?? "") < Date.parse(confirmedAt)
        ? null
        : session,
    enabled,
  });
}
