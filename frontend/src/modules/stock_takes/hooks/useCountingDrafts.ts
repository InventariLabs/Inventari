import { useEffect, useRef, useState } from "react";
import type { StockTake } from "@/modules/stock_takes/types/stock-takes";
import type { StockTakeDiscrepancyCode } from "@/modules/stock_takes/discrepancyCodes";
import {
  countedAmount,
  countedText,
} from "@/modules/stock_takes/countingQuantity";

/** What one row holds in its boxes: a code from the list and the note. */
export interface DraftReason {
  code: StockTakeDiscrepancyCode | "";
  note: string;
}

/**
 * What the reader has typed, and how it is kept in step with the server.
 *
 * The boxes on a counting card are draft state: a number, a note and a
 * reason that have not reached the stock take yet. Everything that counts,
 * filters or summarises reads the stock take's own rows instead — this hook
 * owns only the other half.
 *
 * Seeding runs once per stock take. A background refetch must not overwrite
 * an edit in progress, so it only backfills rows the reader has not touched:
 * the alternative is a count typed on a slow connection disappearing under
 * the answer to a request made before it.
 *
 * A count is kept as the text somebody typed, not as a number. Half of "2.1"
 * is "2.", and a box that reads itself back through a number puts "2" where
 * the dot was — which is how a weighed row lost its decimals before anything
 * was sent. Everything that adds, compares or posts reads the number out of
 * the text with `countedAmount`; an empty box is no count at all, which is a
 * different answer from a count of none.
 */
export function useCountingDrafts(stockTake: StockTake | undefined) {
  const [countedQuantities, setCountedQuantities] = useState<
    Record<string, string>
  >({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, DraftReason>>({});
  // Which rows have had a save attempted — the reason field says what is
  // missing only once somebody has tried, the way every form here does.
  const [triedToSave, setTriedToSave] = useState<Record<string, boolean>>({});

  const seededRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!stockTake?.items) return;
    if (seededRef.current !== stockTake.id) {
      const initialQuantities: Record<string, string> = {};
      const initialNotes: Record<string, string> = {};
      const initialReasons: Record<string, DraftReason> = {};
      stockTake.items.forEach((item) => {
        if (!item.item_id) return;
        initialQuantities[item.item_id] = countedText(item.counted_quantity);
        if (item.notes) initialNotes[item.item_id] = item.notes;
        if (item.discrepancy_reason_code || item.discrepancy_reason) {
          initialReasons[item.item_id] = {
            code: item.discrepancy_reason_code ?? "",
            note: item.discrepancy_reason ?? "",
          };
        }
      });
      setCountedQuantities(initialQuantities);
      setNotes(initialNotes);
      setReasons(initialReasons);
      seededRef.current = stockTake.id;
      return;
    }
    setCountedQuantities((prev) => {
      const next = { ...prev };
      stockTake.items!.forEach((item) => {
        if (item.item_id && next[item.item_id] === undefined) {
          next[item.item_id] = countedText(item.counted_quantity);
        }
      });
      return next;
    });
    setNotes((prev) => {
      const next = { ...prev };
      stockTake.items!.forEach((item) => {
        if (item.item_id && next[item.item_id] === undefined && item.notes) {
          next[item.item_id] = item.notes;
        }
      });
      return next;
    });
  }, [stockTake]);

  // What the boxes hold right now. A scan is answered after a round trip,
  // and the render its handler was made in may already be a count behind.
  // It is updated as the box is, not only when React re-renders: two scans
  // answered back to back must each add to what the previous one left.
  const draftsRef = useRef(countedQuantities);

  /** What the box now holds, exactly as it was typed. */
  const handleQuantityChange = (itemId: string, text: string) => {
    draftsRef.current = { ...draftsRef.current, [itemId]: text };
    setCountedQuantities((prev) => ({ ...prev, [itemId]: text }));
  };

  /** One more, or one fewer — never below nothing on the shelf. */
  const handleQuantityStep = (itemId: string, delta: number) => {
    // Through the same formatter the box uses everywhere else: 4.35 less
    // one step is 3.3499999999999996 in binary floating point, and the
    // number a person reads back off the shelf must not say that.
    const next = countedText(
      Math.max(0, (countedAmount(draftsRef.current[itemId]) ?? 0) + delta),
    );
    draftsRef.current = { ...draftsRef.current, [itemId]: next };
    setCountedQuantities((prev) => ({ ...prev, [itemId]: next }));
  };

  draftsRef.current = countedQuantities;

  /** What the box reads with one more in it, as of now. */
  const oneMoreThan = (itemId: string) =>
    countedText((countedAmount(draftsRef.current[itemId]) ?? 0) + 1);

  return {
    countedQuantities,
    setCountedQuantities,
    notes,
    setNotes,
    reasons,
    setReasons,
    triedToSave,
    setTriedToSave,
    handleQuantityChange,
    handleQuantityStep,
    oneMoreThan,
  };
}
