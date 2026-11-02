import { useCallback, useRef, useState } from "react";
import { useScanResolver } from "@/hooks/useScanResolver";
import type { LabelScanView } from "@/types";
import type {
  CountedLocation,
  StockTakeItem,
} from "@/modules/stock_takes/types/stock-takes";

/** The records a scan names: a record's own label or barcode names one, a
 *  product's catalogue code names every record of that product. */
function recordsNamedBy(result: LabelScanView): string[] {
  if (result.item?.id) return [result.item.id];
  return (result.stock_summary?.items ?? []).map((record) => record.id);
}

interface Options {
  /** The rows of the stock take. */
  lines: StockTakeItem[];
  /** Records standing in the counted place that the list does not hold. */
  outsideItemIds: string[];
  /** One more of this record, saved. */
  onCount: (itemId: string) => void;
  /** A code this count cannot place: it goes back to the search box. */
  onMiss: (code: string) => void;
  /** The locations the count covers — a scanned shelf is read against them. */
  countedLocations: CountedLocation[];
  /** The shelf being counted, once a shelf label was scanned. */
  shelf: CountedLocation | null;
  /** A shelf of this count was scanned: counting goes on there. */
  onShelf: (shelf: CountedLocation) => void;
  /** A location label from outside this count. */
  onShelfOutside: () => void;
  /** Goods of this record found on the current shelf, which has no row of them. */
  onFoundOnShelf: (itemId: string, shelf: CountedLocation) => void;
}

/**
 * A scan on the counting screen is a count, not a lookup.
 *
 * The code goes through the shared scan registry, so a catalogue barcode, a
 * SKU, a record's own barcode and a printed label all name records. Those
 * records are then read against this count: one row is counted and saved,
 * several rows ask which one was meant, a record that stands in the counted
 * place without a row becomes a surplus. A code that names nothing here
 * stays in the search box, where the reader can see what it matches.
 *
 * A location label sets where the count stands, the way a warehouse counts:
 * shelf by shelf. From then on a product is counted on that shelf's row —
 * the shelf answers which row was meant — and goods with no row there are
 * recorded as found on it, wherever the snapshot expected them.
 */
export function useScanCounting({
  lines,
  outsideItemIds,
  onCount,
  onMiss,
  countedLocations,
  shelf,
  onShelf,
  onShelfOutside,
  onFoundOnShelf,
}: Options) {
  const [choices, setChoices] = useState<StockTakeItem[]>([]);

  const { resolve, isResolving } = useScanResolver({
    handle: (result, code) => {
      if (result.action === "set_storage_context" && result.location) {
        const scanned = countedLocations.find(
          (location) => location.id === result.location?.id,
        );
        if (scanned) {
          if ("vibrate" in navigator) navigator.vibrate(100);
          onShelf(scanned);
        } else {
          onShelfOutside();
        }
        return true;
      }
      // A document printout is not a product to count: the shared offer says
      // what it is and where it opens.
      if (result.action === "open_document") return false;
      const named = new Set(recordsNamedBy(result));
      const anywhere = lines.filter(
        (row) => row.item_id && named.has(row.item_id),
      );
      const rows = shelf
        ? anywhere.filter((row) => row.location_id === shelf.id)
        : anywhere;
      if (rows.length > 1) {
        setChoices(rows);
        return true;
      }
      const target =
        rows[0]?.item_id ??
        (shelf ? undefined : outsideItemIds.find((id) => named.has(id)));
      const found = shelf
        ? (anywhere[0]?.item_id ?? outsideItemIds.find((id) => named.has(id)))
        : undefined;
      if (target) {
        if ("vibrate" in navigator) navigator.vibrate(100);
        onCount(target);
      } else if (shelf && found) {
        if ("vibrate" in navigator) navigator.vibrate(100);
        onFoundOnShelf(found, shelf);
      } else {
        onMiss(code);
      }
      return true;
    },
    acceptUnrecognized: (code) => {
      onMiss(code);
      return true;
    },
  });

  const choose = (itemId: string) => {
    setChoices([]);
    onCount(itemId);
  };

  // Distinct codes that arrive while a lookup is in flight are separate count
  // instructions — somebody scanning the next item, not the camera seeing the
  // same symbol again. The shared resolver drops a code while it is busy (its
  // guard is what keeps a held barcode from counting every frame), so the
  // count keeps its own queue and feeds the resolver one code at a time. Each
  // code is answered, and its save started, before the next one is looked up.
  const queueRef = useRef<string[]>([]);
  const drainingRef = useRef(false);
  const resolveRef = useRef(resolve);
  resolveRef.current = resolve;

  const countByCode = useCallback((rawCode: string) => {
    const code = rawCode.trim();
    if (!code) return;
    queueRef.current.push(code);
    if (drainingRef.current) return;
    drainingRef.current = true;
    void (async () => {
      try {
        while (queueRef.current.length > 0) {
          const next = queueRef.current.shift()!;
          await resolveRef.current(next);
        }
      } finally {
        drainingRef.current = false;
      }
    })();
  }, []);

  return {
    countByCode,
    isResolving,
    choices,
    choose,
    dismissChoices: () => setChoices([]),
  };
}
