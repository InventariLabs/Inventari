import { useTranslation } from "react-i18next";
import { ConsumeDialog } from "@/modules/inventory/components/ConsumeDialog";
import { DeleteReasonDialog } from "@/modules/inventory/components/DeleteReasonDialog";
import type { Item } from "@/types";

interface Props {
  deleteReasonItem: Item | null;
  /** Returning a promise keeps the dialog open until the delete settles. */
  onDelete: (item: Item, reason: string, notes: string) => unknown;
  onDeleteCancel: () => void;
  /** The selection a bulk delete is asking a reason for, or null. */
  bulkDeleteIds: string[] | null;
  /** Returning a promise keeps the dialog open until the delete settles. */
  onBulkDelete: (reason: string, notes: string) => unknown;
  onBulkDeleteCancel: () => void;
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
 * The answer-sheets the products list opens: the reason a record — or a
 * whole selection — is being deleted, and the reason a quantity went down.
 * They live here rather than in the page so the page keeps one job.
 */
export function ItemsPageDialogs({
  deleteReasonItem,
  onDelete,
  onDeleteCancel,
  bulkDeleteIds,
  onBulkDelete,
  onBulkDeleteCancel,
  consumeDialogItem,
  onConsume,
  onConsumeCancel,
}: Props) {
  const { t } = useTranslation("items");
  const bulkCount = bulkDeleteIds?.length ?? 0;
  return (
    <>
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

      <DeleteReasonDialog
        key={
          bulkDeleteIds ? `bulk-${bulkDeleteIds.join(",")}` : "no-bulk-delete"
        }
        open={bulkDeleteIds !== null}
        itemName=""
        title={t("messages.confirmBulkDelete", { count: bulkCount })}
        message={t("messages.confirmBulkDeleteBody", { count: bulkCount })}
        onConfirm={onBulkDelete}
        onCancel={onBulkDeleteCancel}
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
