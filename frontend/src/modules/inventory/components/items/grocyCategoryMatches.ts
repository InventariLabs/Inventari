import { categoryLabel } from "@/lib/i18nHelpers";
import type { CategoryDTO } from "@/types";
import type { TranslateFn } from "@/types/i18n";

/**
 * Grocy's product groups that are, by the name this screen shows, categories
 * the organization already has — group name → category id.
 *
 * A seeded category is stored under its English name and shown under its
 * code's translation, so a Polish Grocy's "Nabiał" is the seeded "Dairy" only
 * here, where the translation is. The server takes these matches and files
 * the group's products under that category instead of founding a second
 * "Nabiał" beside it.
 */
export function grocyCategoryMatches(
  groups: string[],
  categories: CategoryDTO[] | undefined,
  t: TranslateFn,
): Record<string, string> {
  const byShownName = new Map<string, string>();
  (categories ?? []).forEach((category) => {
    const shown = categoryLabel(t, category.code, category.name);
    const key = shown.trim().toLowerCase();
    if (!byShownName.has(key)) byShownName.set(key, category.id);
  });
  const matches: Record<string, string> = {};
  groups.forEach((group) => {
    const id = byShownName.get(group.trim().toLowerCase());
    if (id) matches[group] = id;
  });
  return matches;
}
