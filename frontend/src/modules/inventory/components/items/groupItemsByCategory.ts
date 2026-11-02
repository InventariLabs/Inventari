import type { CategoryDTO, Item } from "@/types";
import type { TranslateFn } from "@/types/i18n";

import { categoryLabel } from "@/lib/i18nHelpers";

export type ItemGroup = {
  key: string;
  label: string;
  icon: string | null;
  items: Item[];
};

/**
 * Bucket the page's rows by category, groups ordered by label.
 *
 * The count a header can honestly show is rows-on-this-page: the list
 * paginates server-side, so a whole-set count would promise rows the page
 * does not hold. Whole-set sums live in the footer instead, from
 * /items/aggregates.
 */
export function groupItemsByCategory(
  items: Item[],
  categories: CategoryDTO[] | undefined,
  uncategorizedLabel: string,
  t: TranslateFn,
): ItemGroup[] {
  const byKey = new Map<string, ItemGroup>();
  for (const item of items) {
    const key = item.category_id ?? "uncategorized";
    let group = byKey.get(key);
    if (!group) {
      const category =
        item.category ??
        categories?.find((c) => c.id === item.category_id) ??
        null;
      group = {
        key,
        label: category
          ? categoryLabel(t, category.code, category.name)
          : uncategorizedLabel,
        icon: category?.icon ?? null,
        items: [],
      };
      byKey.set(key, group);
    }
    group.items.push(item);
  }
  return [...byKey.values()].sort((a, b) => a.label.localeCompare(b.label));
}
