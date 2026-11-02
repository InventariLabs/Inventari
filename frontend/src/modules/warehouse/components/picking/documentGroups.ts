import type {
  WmsPickLine,
  WmsPickSession,
} from "@/modules/warehouse/api/documents";

export interface PickDocumentGroup {
  documentId: string;
  number: string;
  lines: WmsPickLine[];
  /** Lines answered: picked in full or closed short. */
  resolved: number;
  /** Lines the document still counts: all but the skipped ones. */
  total: number;
  /** "picking" while a line is pending, "short" when one came up short or was skipped. */
  status: "picking" | "short" | "all_picked";
}

/**
 * The session's lines split by document, in the order the session was
 * started with. Worked out from the lines on screen rather than read from
 * the session's own progress, which is a snapshot from the last response
 * and falls behind with every scan.
 */
export function groupLinesByDocument(
  session: WmsPickSession,
  lines: WmsPickLine[],
): PickDocumentGroup[] {
  return session.documents.map((doc) => {
    const own = lines.filter((ln) => ln.document_id === doc.document_id);
    const counted = own.filter((ln) => ln.status !== "skipped");
    const resolved = counted.filter(
      (ln) => ln.status === "picked" || ln.status === "short",
    ).length;
    const status = own.some((ln) => ln.status === "pending")
      ? "picking"
      : own.some((ln) => ln.status === "short" || ln.status === "skipped")
        ? "short"
        : "all_picked";
    return {
      documentId: doc.document_id,
      number: doc.document_number,
      lines: own,
      resolved,
      total: counted.length,
      status,
    };
  });
}
