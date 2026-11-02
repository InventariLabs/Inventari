import { useCallback, useEffect, useState } from "react";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";

export interface BulkRefusal {
  doc: WarehouseDocumentRow;
  error: unknown;
}

interface UseBulkSelectOptions {
  documents: WarehouseDocumentRow[];
  deleteMutation: {
    mutate: (
      id: string,
      callbacks?: {
        onSuccess?: () => void;
        onError?: (error: unknown) => void;
      },
    ) => void;
  };
  confirmMutation: {
    mutate: (
      id: string,
      callbacks?: {
        onSuccess?: () => void;
        onError?: (error: unknown) => void;
      },
    ) => void;
  };
  /** Told once the whole selection has been tried: how many drafts went
   *  through and which ones were refused, each with the server's reason. */
  onConfirmed?: (confirmed: number, refused: BulkRefusal[]) => void;
  onSuccess?: (count: number) => void;
  /** The count, and the first refusal the server gave — "you do not have
   *  permission" reads very differently from "failed to delete 1 document",
   *  and the caller could not tell them apart without it. */
  onError?: (count: number, error: unknown) => void;
}

export function useBulkSelect({
  documents,
  deleteMutation,
  confirmMutation,
  onConfirmed,
  onSuccess,
  onError,
}: UseBulkSelectOptions) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);
  const [isBulkConfirming, setIsBulkConfirming] = useState(false);

  // The selection describes the list on screen. A tick that survives a page
  // or filter change kept counting in the bar while every action was built
  // from the rows in view, so a "Pick 2 selected" session covered one
  // document. When the list no longer carries an id, its tick goes with it;
  // a refetch of the same rows leaves the selection alone.
  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev;
      const present = new Set(documents.map((document) => document.id));
      const next = new Set([...prev].filter((id) => present.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [documents]);

  const selectedDocs = documents.filter((d) => selectedIds.has(d.id));
  const selectedDrafts = selectedDocs.filter((d) => d.status === "DRAFT");
  // A printout exists only once a document is confirmed — the same two
  // statuses the server prints.
  const selectedPrintable = selectedDocs.filter(
    (d) => d.status === "CONFIRMED" || d.status === "COMPLETED",
  );

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === documents.length) return new Set();
      return new Set(documents.map((d) => d.id));
    });
  }, [documents]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const handleBulkConfirm = async () => {
    setIsBulkConfirming(true);
    let confirmed = 0;
    const refused: BulkRefusal[] = [];
    // One at a time, in list order: each confirmation books stock and the
    // next may depend on what the previous one left on the shelf.
    for (const doc of selectedDrafts) {
      try {
        await new Promise<void>((resolve, reject) => {
          confirmMutation.mutate(doc.id, {
            onSuccess: () => resolve(),
            onError: (error) => reject(error),
          });
        });
        confirmed++;
      } catch (error: unknown) {
        refused.push({ doc, error });
      }
    }
    setIsBulkConfirming(false);
    setBulkConfirmOpen(false);
    onConfirmed?.(confirmed, refused);
    // What was refused stays selected: the reader fixes it and tries again
    // without picking those rows out of the list a second time.
    const refusedIds = new Set(refused.map((r) => r.doc.id));
    setSelectedIds(
      (prev) => new Set([...prev].filter((id) => refusedIds.has(id))),
    );
  };

  const handleBulkDelete = async () => {
    setIsBulkDeleting(true);
    let success = 0;
    let failed = 0;
    let firstError: unknown = null;
    for (const doc of selectedDrafts) {
      try {
        await new Promise<void>((resolve, reject) => {
          deleteMutation.mutate(doc.id, {
            onSuccess: () => resolve(),
            onError: (error) => reject(error),
          });
        });
        success++;
      } catch (error: unknown) {
        failed++;
        if (firstError === null) firstError = error;
      }
    }
    setIsBulkDeleting(false);
    setBulkDeleteOpen(false);
    onSuccess?.(success);
    onError?.(failed, firstError);
    clearSelection();
  };

  return {
    selectedIds,
    selectedDocs,
    selectedDrafts,
    selectedPrintable,
    bulkConfirmOpen,
    isBulkConfirming,
    setBulkConfirmOpen,
    handleBulkConfirm,
    bulkDeleteOpen,
    isBulkDeleting,
    setBulkDeleteOpen,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    handleBulkDelete,
  };
}
