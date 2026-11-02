import type { PartnerPricelist } from "../api/pricelist";

/**
 * Which entries answer the same question, and which of them procurement takes.
 *
 * Two rows for one supplier's one product over the same dates and the same
 * minimum quantity are two answers to one question, and nothing on the screen
 * said so — both were ordinary rows. `get_best_price_async` orders by price,
 * so the cheaper one is what reaches an order; a buyer who corrected the
 * dearer row watched the old number keep coming back.
 *
 * The API refuses a third one now. This is for the pairs already in the
 * table, which no write path is going to remove on its own.
 */
export interface DuplicateVerdict {
  /** Ids of every entry that shares its key with another. */
  shadowed: Set<string>;
  /** Ids of the entry procurement actually reads, one per duplicated key. */
  effective: Set<string>;
}

function key(entry: PartnerPricelist): string {
  return [
    entry.product_template_id,
    entry.valid_from,
    entry.valid_to ?? "",
    entry.min_quantity ?? "",
  ].join("|");
}

export function findDuplicates(entries: PartnerPricelist[]): DuplicateVerdict {
  const groups = new Map<string, PartnerPricelist[]>();
  for (const entry of entries) {
    const k = key(entry);
    const group = groups.get(k);
    if (group) group.push(entry);
    else groups.set(k, [entry]);
  }

  const shadowed = new Set<string>();
  const effective = new Set<string>();
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    // Lowest price wins, because that is what the query does — not because
    // it is the right answer. Saying which one is read is the whole point.
    const winner = group.reduce((best, entry) =>
      Number(entry.unit_price) < Number(best.unit_price) ? entry : best,
    );
    effective.add(winner.id);
    for (const entry of group) {
      if (entry.id !== winner.id) shadowed.add(entry.id);
    }
  }
  return { shadowed, effective };
}
