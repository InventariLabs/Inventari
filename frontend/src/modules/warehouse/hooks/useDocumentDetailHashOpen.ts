import { useEffect } from "react";

/** The doc fields the hash effects read — structural on purpose, the way
 * `confirmDialogMessage` in the page takes its doc. */
interface HashOpenDoc {
  status: string;
  type: string;
}

/** Opens the page's modals from the URL hash, kept here so the page's render
 * stays a render: `#edit` on a DRAFT (the CTA on the rejected banner —
 * without this handler the link would be a dead anchor), and on a CONFIRMED
 * document `#receive`, `#pick` and `#execute` open the floor flow straight
 * from a scanned printout — the same hashes the ScanPage derives from the
 * scan response's document_mode.
 */
export function useDocumentDetailHashOpen(
  hash: string,
  doc: HashOpenDoc | undefined,
  setEditOpen: (open: boolean) => void,
  setReceivingOpen: (open: boolean) => void,
  setPickingOpen: (open: boolean) => void,
  setExecutionOpen: (open: boolean) => void,
): void {
  useEffect(() => {
    if (hash === "#edit" && doc?.status === "DRAFT") {
      setEditOpen(true);
    }
  }, [hash, doc?.status, setEditOpen]);

  useEffect(() => {
    if (
      hash === "#receive" &&
      doc?.status === "CONFIRMED" &&
      ["IN", "INTERNAL_IN"].includes(doc.type)
    ) {
      setReceivingOpen(true);
    }
  }, [hash, doc?.status, doc?.type, setReceivingOpen]);

  useEffect(() => {
    if (
      hash === "#pick" &&
      doc?.status === "CONFIRMED" &&
      ["OUT", "INT", "INTERNAL_OUT"].includes(doc.type)
    ) {
      setPickingOpen(true);
    }
  }, [hash, doc?.status, doc?.type, setPickingOpen]);

  useEffect(() => {
    if (
      hash === "#execute" &&
      doc?.status === "CONFIRMED" &&
      doc.type !== "CORRECTION"
    ) {
      setExecutionOpen(true);
    }
  }, [hash, doc?.status, doc?.type, setExecutionOpen]);
}
