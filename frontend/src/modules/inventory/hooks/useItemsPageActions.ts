import { useCallback, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { itemsApi } from "@/lib/api/items";
import { extractApiError } from "@/lib/errors";
import {
  useConsumeItem,
  useDeleteItem,
  useDiscardItem,
  useUpdateItemQuantity,
} from "@/modules/inventory/hooks/useItemMutations";
import { downloadBlob } from "@/utils/helpers";
import { getTodayFilename, toAmount } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import {
  isDisposalReason,
  reasonLabelKey,
  type StockReason,
} from "@/modules/inventory/constants/stockReasons";
import type { Item, StorageLocationSummary } from "@/types";
import type { ItemAggregatesParams } from "./useItems";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";

interface UseItemsPageActionsParams {
  items: Item[];
  storageFilter: string;
  /** The list's own query params, so the sheet holds the rows on screen. */
  exportParams: ItemAggregatesParams;
  storages?: StorageLocationSummary[];
  setConsumeDialogItem: (item: Item | null) => void;
  setDeleteReasonItem: (item: Item | null) => void;
}

/**
 * Action handlers + mutations for the Items page (delete, consume, stock
 * quick-actions, export). Extracted from ItemsPage.tsx to keep the page
 * component focused on rendering.
 */
export function useItemsPageActions({
  items,
  storageFilter,
  exportParams,
  storages,
  setConsumeDialogItem,
  setDeleteReasonItem,
}: UseItemsPageActionsParams) {
  const { t } = useTranslation(["items", "labels", "common"]);
  const navigate = useNavigate();
  const { dialogState, showConfirm, closeDialog } = useConfirmDialog();

  const deleteItemMutation = useDeleteItem();
  const deleteMutation = useMemo(
    () => ({
      mutate: (itemId: string, reason?: string, notes?: string) =>
        deleteItemMutation.mutate(
          { itemId, reason, notes },
          { onSuccess: () => toast.success(t("messages.itemDeleted")) },
        ),
      // For the reason dialog, which has to know whether the delete happened:
      // the rejection keeps it open with the reason and note still typed in,
      // instead of closing over a delete that never took place.
      mutateAsync: async (itemId: string, reason?: string, notes?: string) => {
        await deleteItemMutation.mutateAsync({ itemId, reason, notes });
        toast.success(t("messages.itemDeleted"));
      },
      isPending: deleteItemMutation.isPending,
      variables: deleteItemMutation.variables,
    }),
    [deleteItemMutation, t],
  );

  const consumeItemMutation = useConsumeItem();
  const discardItemMutation = useDiscardItem();
  const consumeMutation = useMemo(() => {
    // The reader picked a reason; the confirmation has to say it back —
    // "used up" after picking "Expired" reports a different event than the
    // one that just happened.
    const finishedMessage = (reason: string) =>
      reason === "USED"
        ? t("labels:quickAdd.finished")
        : t("items:quickActions.finishedWithReason", {
            reason: t(reasonLabelKey(reason as StockReason)),
          });
    const consumedMessage = (reason: string, updatedItem: Item) =>
      reason === "USED"
        ? t("items:quickActions.consumedSuccessRemaining", {
            remaining: formatQuantityLocalized(
              t,
              updatedItem.quantity,
              updatedItem.uom?.symbol,
              updatedItem.uom?.rounding,
            ),
          })
        : t("items:quickActions.consumedSuccessWithReason", {
            reason: t(reasonLabelKey(reason as StockReason)),
            remaining: formatQuantityLocalized(
              t,
              updatedItem.quantity,
              updatedItem.uom?.symbol,
              updatedItem.uom?.rounding,
            ),
          });
    // Consuming the last unit files the record under the virtual Consumed
    // location, so it vanishes from this list — say so, and hand the way
    // back: the detail page still opens for a record with nothing left.
    const usedUpToastOptions = (itemId: string) => ({
      description: t("items:quickActions.recordLeftList"),
      action: {
        label: t("items:quickActions.openRecord"),
        onClick: () => navigate(`/inventory/items/${itemId}`),
      },
    });
    // Thrown out is not used up: a disposal reason goes to the discard
    // endpoint, whose action the ledger, the journal and the waste report
    // can tell apart from a use. Routed through consume, every bin read as
    // 0.00 wasted and the journal said "Use" beside the word "DISPOSED".
    const stockExitMutation = (reason: string) =>
      isDisposalReason(reason) ? discardItemMutation : consumeItemMutation;
    return {
      mutate: (itemId: string, quantity = 1, reason = "USED", notes?: string) =>
        stockExitMutation(reason).mutate(
          { itemId, quantity, reason, notes },
          {
            onSuccess: (updatedItem) => {
              if (updatedItem.is_deleted) {
                toast.success(finishedMessage(reason));
              } else if ((toAmount(updatedItem.quantity) ?? 0) <= 0) {
                toast.success(
                  finishedMessage(reason),
                  usedUpToastOptions(itemId),
                );
              } else {
                toast.success(consumedMessage(reason, updatedItem));
              }
            },
            onError: (error: unknown) => {
              toast.error(
                extractApiError(
                  error,
                  isDisposalReason(reason)
                    ? t("items:quickActions.discardFailed")
                    : t("items:quickActions.consumeFailed"),
                ),
              );
            },
          },
        ),
      mutateAsync: async (
        itemId: string,
        quantity = 1,
        reason = "USED",
        notes?: string,
      ) => {
        const updatedItem = await stockExitMutation(reason).mutateAsync({
          itemId,
          quantity,
          reason,
          notes,
        });
        if (updatedItem.is_deleted) {
          toast.success(finishedMessage(reason));
        } else if ((toAmount(updatedItem.quantity) ?? 0) <= 0) {
          toast.success(finishedMessage(reason), usedUpToastOptions(itemId));
        } else {
          toast.success(consumedMessage(reason, updatedItem));
        }
      },
      isPending: consumeItemMutation.isPending || discardItemMutation.isPending,
      variables: consumeItemMutation.variables ?? discardItemMutation.variables,
    };
  }, [consumeItemMutation, discardItemMutation, t, navigate]);

  const handleConsume = useCallback(
    (id: string) => {
      const item = items.find((i) => i.id === id);
      if (item) setConsumeDialogItem(item);
    },
    [items, setConsumeDialogItem],
  );

  /** One way to delete a record, and it asks why. The row used to open a
   * plain "are you sure?" while the edit modal asked for a reason, so the
   * reason on file said more about which button people reach for than about
   * what happened to the things. */
  const handleDelete = useCallback(
    (id: string) => {
      const item = items.find((i) => i.id === id);
      if (item) setDeleteReasonItem(item);
    },
    [items, setDeleteReasonItem],
  );

  /** Swipe-to-delete on a card: the five-second Undo window *is* the
   * confirmation, so this path deletes straight away. Routing it through
   * `handleDelete` made the toast lie — it said the product was removed and
   * then asked for permission five seconds later. */
  const handleSwipeDelete = useCallback(
    (id: string) => {
      deleteMutation.mutate(id);
    },
    [deleteMutation],
  );

  /** Deleting a whole selection: one confirmation, then the same per-item
   * delete the row action uses. */
  const handleBulkDelete = useCallback(
    (ids: string[], onDone?: () => void) => {
      if (ids.length === 0) return;
      showConfirm({
        // The question carries the number: a singular "this product" over
        // "Delete 4 selected products?" asked about a different thing than
        // the one the button was about to do. The body carries it too, so it
        // agrees with the title when one row is selected.
        title: t("items:messages.confirmBulkDelete", { count: ids.length }),
        message: t("items:messages.confirmBulkDeleteBody", {
          count: ids.length,
        }),
        confirmText: t("actions.delete"),
        cancelText: t("actions.cancel"),
        variant: "danger",
        onConfirm: async () => {
          await Promise.all(
            ids.map((itemId) => deleteItemMutation.mutateAsync({ itemId })),
          );
          toast.success(t("items:messages.itemDeleted", { count: ids.length }));
          onDone?.();
        },
      });
    },
    [showConfirm, t, deleteItemMutation],
  );

  const updateQuantityMutation = useUpdateItemQuantity();
  /** The counterpart of "Remove 1 unit", offered beside it rather than one
   *  click deeper in the actions sheet. */
  const handleAddOne = useCallback(
    (id: string) => {
      const item = items.find((i) => i.id === id);
      if (!item) return;
      updateQuantityMutation.mutate(
        { itemId: id, quantity: (Number(item.quantity) || 0) + 1 },
        {
          onSuccess: (updated) =>
            toast.success(
              t("items:quickActions.addedOneSuccess", {
                remaining: formatQuantityLocalized(
                  t,
                  updated.quantity,
                  updated.uom?.symbol,
                  updated.uom?.rounding,
                ),
              }),
            ),
        },
      );
    },
    [items, updateQuantityMutation, t],
  );

  // The params object is rebuilt every render; the page mounts this handler
  // in the header inside an effect, so a handler that changed with the
  // params would re-set the header on every render, without end.
  const exportParamsRef = useRef(exportParams);
  exportParamsRef.current = exportParams;

  const handleExport = useCallback(async () => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "items-export" });
      const blob = await itemsApi.exportXlsx(exportParamsRef.current);
      const storageName = storages?.find((s) => s.id === storageFilter)?.name;
      downloadBlob(
        blob,
        `inventory${storageName ? `_${storageName.toLowerCase().replace(/\s+/g, "_")}` : ""}_${getTodayFilename()}.xlsx`,
      );
      toast.success(t("common:actions.exportSuccess"), { id: "items-export" });
    } catch (error) {
      toast.error(extractApiError(error, t("common:actions.exportError")), {
        id: "items-export",
      });
    }
  }, [storageFilter, storages, t]);

  return {
    dialogState,
    showConfirm,
    closeDialog,
    deleteMutation,
    consumeMutation,
    handleConsume,
    handleAddOne,
    handleDelete,
    handleSwipeDelete,
    handleBulkDelete,
    handleExport,
  };
}
