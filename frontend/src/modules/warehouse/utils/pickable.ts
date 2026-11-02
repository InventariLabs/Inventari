/** A dispatch a picking session can be opened over: confirmed, and leaving the
 *  warehouse. The document list's selection bar and the floor's queue ask the
 *  same question, so they ask it here. */
export function isPickable(doc: {
  type?: string | null;
  status?: string | null;
}) {
  return (
    (doc.type === "OUT" || doc.type === "INTERNAL_OUT") &&
    doc.status === "CONFIRMED"
  );
}
