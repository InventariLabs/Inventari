import type { TFunction } from "i18next";

/**
 * How the group a category belongs to is written on screen.
 *
 * A seeded group code gets its translation if the locale has one, so the food
 * profile does not start speaking English at a Polish reader; anything else —
 * an organisation's own label, a code from another vertical — renders exactly
 * as typed. The codes live in `categories:groups.*`, not in a map here: this
 * belongs to no vertical and has no business naming one vertical's furniture.
 *
 * Shared rather than private to the categories list, which is what let the
 * category form offer "FREEZER", "FRIDGE" and "PANTRY" in a Polish interface
 * while the list two clicks away called the same three things "Zamrażarka",
 * "Lodówka" and "Spiżarnia".
 */
export function categoryGroupLabel(t: TFunction, group: string): string {
  return t(`categories:groups.${group}`, { defaultValue: group });
}

/**
 * The group a category is in, or null.
 *
 * `group_label` and nothing else: one source, and the organisation owns it.
 */
export function categoryGroup(category: {
  group_label?: string | null;
}): string | null {
  return category.group_label ?? null;
}

/** The distinct groups present in a set of categories, sorted. */
export function categoryGroups(
  categories: readonly { group_label?: string | null }[],
): string[] {
  const groups = new Set<string>();
  for (const category of categories) {
    const group = categoryGroup(category);
    if (group) groups.add(group);
  }
  return Array.from(groups).sort();
}
