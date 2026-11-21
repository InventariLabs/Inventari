import { useCallback, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { itemsApi } from "@/lib/api/items";
import { extractApiError } from "@/lib/errors";
import type { Item, LabelScanView } from "@/types";
import { ConsumeDialog } from "@/modules/inventory/components/ConsumeDialog";
import { useScanConsume } from "./useScanActions";

/**
 * Taking stock off a scanned label: one unit of the record with the nearest
 * expiry.
 *
 * The button under the list says "Remove 1 (first to expire)", and this is the
 * only entry to that rule; it takes one unit, not the whole record, so a
 * reader asking for one kilogram keeps the other. The per-location "−" asks
 * the same question and answers it the same way. A record holding less than
 * one unit cannot give "1": the sheet asks how much instead, the way the
 * product list does.
 */
export function useScanStockConsume(
  scanned: LabelScanView | null,
  refreshStockSheet: () => Promise<void>,
): {
  consumeFrom: (itemId?: string) => Promise<void>;
  consumeDialog: ReactNode;
} {
  const { t } = useTranslation("scan");
  const consumeMutation = useScanConsume();
  const [askingItem, setAskingItem] = useState<Item | null>(null);

  const consumeFrom = useCallback(
    async (itemId?: string) => {
      const items = scanned?.stock_summary?.items ?? [];
      let itemToConsumeId = itemId;
      if (!itemToConsumeId && items.length) {
        itemToConsumeId = [...items].sort((a, b) => {
          if (!a.expiry_date) return 1;
          if (!b.expiry_date) return -1;
          return (
            new Date(a.expiry_date).getTime() -
            new Date(b.expiry_date).getTime()
          );
        })[0].id;
      }
      if (!itemToConsumeId) return;

      try {
        const record = items.find((it) => it.id === itemToConsumeId);
        if (record && record.quantity < 1) {
          setAskingItem(await itemsApi.getById(itemToConsumeId));
          return;
        }
        await consumeMutation.mutateAsync({
          itemId: itemToConsumeId,
          quantity: 1,
        });
        await refreshStockSheet();
      } catch (error: unknown) {
        // "Error while removing from stock" reads as a breakage; a refusal
        // reads as one too unless the server's own sentence is allowed through.
        toast.error(extractApiError(error, t("errorConsuming")));
      }
    },
    [scanned, consumeMutation, refreshStockSheet, t],
  );

  const consumeDialog = askingItem ? (
    <ConsumeDialog
      open
      item={askingItem}
      onConfirm={async (quantity, reason, notes) => {
        await consumeMutation.mutateAsync({
          itemId: askingItem.id,
          quantity,
          reason,
          notes,
        });
        setAskingItem(null);
        await refreshStockSheet();
      }}
      onCancel={() => setAskingItem(null)}
    />
  ) : null;

  return { consumeFrom, consumeDialog };
}
