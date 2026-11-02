import type { StorageLocationSummary } from "@/types";
import type { TranslateFn } from "@/types/i18n";

/**
 * What a location delete rebuilds, in the sentences its question adds.
 *
 * The direct children move up a level, and every record standing anywhere
 * inside the subtree — across modules — changes its place with them. Both
 * numbers are counted on the server from the full organization tree: a child
 * the listing hides (archived, or dropped by its module filter) moves all the
 * same, and so do the records standing in it. Those are exactly the ones the
 * reader cannot match against the rows on screen, so where the list shows
 * fewer than move, a sentence says how many it does not show — the true
 * number stays, and nothing on screen contradicts it.
 *
 * `undefined` for a row the caller could not hand over: no sentence, never a
 * number the server did not count.
 */
export function locationDeleteConsequences(
  t: TranslateFn,
  row:
    | Pick<
        StorageLocationSummary,
        | "direct_children_count"
        | "listed_children_count"
        | "subtree_items_count"
        | "total_subtree_items_count"
      >
    | undefined,
): string {
  if (!row) return "";
  const sentences: string[] = [];
  const notListed = (moving: number, shown: number) => {
    if (moving > shown) {
      sentences.push(
        t("locations:edit.deleteNotListed", { count: moving - shown }),
      );
    }
  };
  const children = row.direct_children_count;
  if (children > 0) {
    sentences.push(
      t("locations:edit.deleteMovesLocations", { count: children }),
    );
    notListed(children, row.listed_children_count);
  }
  const records = row.total_subtree_items_count;
  if (records > 0) {
    sentences.push(t("locations:edit.deleteMovesRecords", { count: records }));
    notListed(records, row.subtree_items_count);
  }
  return sentences.map((sentence) => ` ${sentence}`).join("");
}
