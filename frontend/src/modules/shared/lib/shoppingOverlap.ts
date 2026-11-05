import type { components } from "@/types/api-generated";

/** A line just written that another open shopping list still asks for. */
export type ListedElsewhere = components["schemas"]["ListedElsewhere"];

type Translate = (key: string, opts?: Record<string, unknown>) => string;

/**
 * The sentence for goods a freshly written shopping list shares with another
 * open one, or `null` when nothing overlaps.
 *
 * Every screen that writes a list through the recipes module gets the same
 * answer and says it the same way: grouped by the list the goods stand on,
 * so "Flour, Eggs on A; Eggs on B" says which goods are where. The server's
 * order is kept — lists oldest first, goods by name.
 */
export function onOtherListsMessage(
  t: Translate,
  lines: readonly ListedElsewhere[] | undefined,
): string | null {
  if (!lines || lines.length === 0) return null;
  const byList = new Map<string, { name: string; names: string[] }>();
  for (const line of lines) {
    const entry = byList.get(line.list_id) ?? {
      name: line.list_name,
      names: [],
    };
    if (!entry.names.includes(line.name)) entry.names.push(line.name);
    byList.set(line.list_id, entry);
  }
  const where = [...byList.values()]
    .map((entry) =>
      t("common:shoppingOverlap.onList", {
        names: entry.names.join(", "),
        list: entry.name,
      }),
    )
    .join("; ");
  return t("common:shoppingOverlap.toast", { where });
}
