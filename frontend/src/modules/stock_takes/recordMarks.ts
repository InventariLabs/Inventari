import type { TranslateFn } from "@/types/i18n";
import type { Item } from "@/types";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { formatDate, formatDateTime } from "@/utils/formatters";

/** Which of several otherwise identical records a row is, and when it was
 * added — the receipt or putaway that left it. */
export interface Twin {
  position: number;
  of: number;
  added: string | null;
}

/**
 * What tells one record of a product from another on the same shelf: its
 * batch and the date it expires. Two bananas in one fridge are two rows of
 * the count, and with the expected quantity hidden by a blind count these
 * are the only words that differ — the card prints them and every control
 * on it carries them in its name. The scan chooser tells the rows apart the
 * same way.
 */
export function recordMarks(
  t: TranslateFn,
  item: Pick<Item, "effective_expiry_date"> | undefined,
  stockTakeItem: Pick<StockTakeItem, "lot_name"> | undefined,
  /** Which of several otherwise identical records this is. */
  twin?: Twin | null,
): string[] {
  const marks: string[] = [];
  if (stockTakeItem?.lot_name) {
    marks.push(t("stock_takes:item.lot", { lot: stockTakeItem.lot_name }));
  }
  const expiry = item?.effective_expiry_date;
  if (expiry)
    marks.push(t("stock_takes:scan.expires", { date: formatDate(expiry) }));
  // Receipts into one place leave one record each, and nothing about them
  // differs but where they came from: say which of them this row is, and
  // when the receipt or putaway that left it was booked.
  if (twin) {
    marks.push(
      t("stock_takes:item.record", { position: twin.position, of: twin.of }),
    );
    if (twin.added)
      marks.push(
        t("stock_takes:item.added", { date: formatDateTime(twin.added) }),
      );
  }
  return marks;
}

/**
 * Numbers the rows that share a key — the same product, batch, expiry and
 * place — in the order their records were added, so neither the eye nor a
 * screen reader meets the same row twice. Rows with no sibling get no number.
 */
export function numberTwins<Id>(
  rows: { id: Id; key: string; added: string }[],
  idOrder: (a: Id, b: Id) => number,
): Map<Id, Twin> {
  const groups = new Map<string, typeof rows>();
  for (const row of rows) {
    groups.set(row.key, [...(groups.get(row.key) ?? []), row]);
  }
  const twinOf = new Map<Id, Twin>();
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    [...group]
      .sort((a, b) => a.added.localeCompare(b.added) || idOrder(a.id, b.id))
      .forEach((row, index) =>
        twinOf.set(row.id, {
          position: index + 1,
          of: group.length,
          added: row.added || null,
        }),
      );
  }
  return twinOf;
}
