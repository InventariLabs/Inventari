import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ConsumeDialog } from "@/modules/inventory/components/ConsumeDialog";
import { DeleteReasonDialog } from "@/modules/inventory/components/DeleteReasonDialog";
import type { ConfirmDialogState } from "@/hooks/useConfirm";
import type { Item } from "@/types";

interface Props {
  dialogState: ConfirmDialogState;
  closeDialog: () => void;
  deleteReasonItem: Item | null;
  /** Returning a promise keeps the dialog open until the delete settles. */
  onDelete: (item: Item, reason: string, notes: string) => unknown;
  onDeleteCancel: () => void;
  consumeDialogItem: Item | null;
  onConsume: (
    item: Item,
    quantity: number,
    reason: string,
    notes?: string,
  ) => unknown;
  onConsumeCancel: () => void;
}

/**
 * The three answer-sheets the products list opens: a plain confirmation, the
 * reason a record is being deleted, and the reason a quantity went down.
 * They live here rather than in the page so the page keeps one job.
 */
export function ItemsPageDialogs({
  dialogState,
  closeDialog,
  deleteReasonItem,
  onDelete,
  onDeleteCancel,
  consumeDialogItem,
  onConsume,
  onConsumeCancel,
}: Props) {
  return (
    <>
      <ConfirmDialog
        open={dialogState.isOpen}
        onCancel={closeDialog}
        onConfirm={dialogState.onConfirm}
        title={dialogState.title}
        message={dialogState.message}
        confirmLabel={dialogState.confirmText}
        cancelLabel={dialogState.cancelText}
        variant={dialogState.variant}
      />

      <DeleteReasonDialog
        key={deleteReasonItem?.id ?? "no-delete"}
        open={deleteReasonItem !== null}
        itemName={deleteReasonItem?.name ?? ""}
        onConfirm={(reason, notes) =>
          deleteReasonItem
            ? onDelete(deleteReasonItem, reason, notes)
            : undefined
        }
        onCancel={onDeleteCancel}
      />

      <ConsumeDialog
        key={consumeDialogItem?.id ?? "closed"}
        open={consumeDialogItem !== null}
        item={consumeDialogItem}
        onConfirm={(quantity, reason, notes) =>
          consumeDialogItem
            ? onConsume(consumeDialogItem, quantity, reason, notes)
            : undefined
        }
        onCancel={onConsumeCancel}
      />
    </>
  );
}
