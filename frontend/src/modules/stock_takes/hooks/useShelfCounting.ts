import { useState, type MutableRefObject } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractApiError, extractApiErrorField } from "@/lib/errors";
import { toAmount } from "@/utils/formatters";
import {
  countedAmount,
  countedText,
} from "@/modules/stock_takes/countingQuantity";
import type {
  CountedLocation,
  StockTake,
} from "@/modules/stock_takes/types/stock-takes";
import {
  useCloseStockTakeLocation,
  type useAddStockTakeItem,
  type useCountStockTakeItem,
} from "@/modules/stock_takes/hooks/useStockTakes";
import type { useConfirm } from "@/hooks/useConfirm";

interface Options {
  /** The count as the server holds it: its rows and its place. */
  stockTake: StockTake | undefined;
  confirm: ReturnType<typeof useConfirm>["confirm"];
  /** Whether a row's boxes hold something the server does not know yet. */
  isUnsaved: (itemId: string) => boolean;
  surplusMutation: ReturnType<typeof useAddStockTakeItem>;
  countMutation: ReturnType<typeof useCountStockTakeItem>;
  /** The counting screen's save queue: a find waits for the saves before it. */
  savesRef: MutableRefObject<Promise<void>>;
  /** Marks a save as in flight, so finishing waits for it like for any save. */
  trackSave: (saved: Promise<void>) => Promise<void>;
  /** Rows the surplus endpoint created, by record, before the list shows them. */
  createdLinesRef: MutableRefObject<Record<string, string>>;
  handleQuantityChange: (itemId: string, text: string) => void;
  oneMoreThan: (itemId: string) => string;
  /** A shelf scan or a find was taken: the code leaves the search box. */
  onDone: () => void;
}

/**
 * Counting by location: which shelf the count stands at, and what is found
 * on it.
 *
 * A scanned label of a location the count covers sets the shelf; the list
 * narrows to its rows and a product scanned next is counted there. Goods
 * with no row on that shelf are recorded as found on it — the first find
 * opens the row (and, where the goods were expected on another shelf, a
 * record of them on this one — or, for a unit with a serial number, moves its
 * own row here); the server answers a second find with the row it already
 * has, which then gets one more like any scanned row.
 */
export function useShelfCounting({
  stockTake,
  confirm,
  isUnsaved,
  surplusMutation,
  countMutation,
  savesRef,
  trackSave,
  createdLinesRef,
  handleQuantityChange,
  oneMoreThan,
  onDone,
}: Options) {
  const { t } = useTranslation(["stock_takes"]);
  const [shelf, setShelf] = useState<CountedLocation | null>(null);
  const closeMutation = useCloseStockTakeLocation(stockTake?.id);

  /**
   * Done with the shelf: what nobody counted on it is counted as 0, and a
   * shelf with nothing on it is confirmed as empty. The confirmation names
   * how many rows that is and never what they held — a blind count stays
   * blind. A number still in its box would be overwritten by that 0, so the
   * shelf is not closed over one.
   */
  const closeShelf = async () => {
    if (!shelf) return;
    const onShelf = (stockTake?.items ?? []).filter(
      (line) => line.location_id === shelf.id,
    );
    const unsaved = onShelf.filter(
      (line) => line.item_id && isUnsaved(line.item_id),
    ).length;
    if (unsaved > 0) {
      toast.error(t("shelf.closeUnsaved", { count: unsaved }));
      return;
    }
    const uncounted = onShelf.filter((line) => line.counted_quantity == null);
    const empty = onShelf.every(
      (line) => toAmount(line.counted_quantity) === 0,
    );
    const location = shelf.path;
    const message =
      uncounted.length > 0
        ? t("shelf.closeUncounted", { count: uncounted.length, location })
        : empty
          ? t("shelf.closeEmpty", { location })
          : t("shelf.closeCounted", { location });
    const proceed = await confirm({
      title: t("shelf.closeTitle"),
      message,
      confirmLabel: t("shelf.closeConfirm"),
    });
    if (!proceed) return;
    // A scan still on its way is part of the shelf's count, not a row to zero.
    await savesRef.current;
    closeMutation.mutate(shelf.id, {
      onSuccess: (closed) => {
        for (const line of uncounted) {
          if (line.item_id) handleQuantityChange(line.item_id, "0");
        }
        // What closing changed comes first: rows counted as 0 are the news.
        toast.success(
          closed.counted_as_zero > 0
            ? t("shelf.closedDone", { count: closed.counted_as_zero, location })
            : closed.empty
              ? t("shelf.closedEmptyDone", { location })
              : t("shelf.closedCountedDone", { location }),
        );
      },
    });
  };

  const countFoundOnShelf = (itemId: string, onShelf: CountedLocation) => {
    onDone();
    const write = async () => {
      try {
        const created = await surplusMutation.mutateAsync({
          itemId,
          quantity: 1,
          shelfId: onShelf.id,
        });
        if (!created.item_id) return;
        createdLinesRef.current[created.item_id] = created.id;
        handleQuantityChange(
          created.item_id,
          countedText(created.counted_quantity),
        );
      } catch (error) {
        const lineId = extractApiErrorField(error, "stock_take_item_id");
        const recordId = extractApiErrorField(error, "item_id");
        if (!lineId || !recordId) throw error;
        createdLinesRef.current[recordId] = lineId;
        const next = oneMoreThan(recordId);
        handleQuantityChange(recordId, next);
        await countMutation.mutateAsync({
          stockTakeItemId: lineId,
          quantity: countedAmount(next) ?? 0,
        });
      }
    };
    savesRef.current = trackSave(
      savesRef.current.then(write).catch((error: Error) => {
        toast.error(extractApiError(error, t("errors.saveFailed")));
      }),
    );
  };

  return {
    shelf,
    /** Stand at a shelf of this count, or at none (`null`: the whole location). */
    setShelf: (next: CountedLocation | null) => {
      setShelf(next);
      onDone();
    },
    countFoundOnShelf,
    closeShelf,
    isClosing: closeMutation.isPending,
    /**
     * A location label from outside the count: refused, naming the count's
     * place. The counter now stands somewhere this count does not cover, so
     * the shelf set before it no longer says where they are.
     */
    refuseShelfOutside: () => {
      setShelf(null);
      onDone();
      toast.error(
        t("shelf.outside", {
          location: stockTake?.location_name ?? "",
        }),
      );
    },
  };
}
