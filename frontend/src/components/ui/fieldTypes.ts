import type { FieldDefinition, FieldType } from "@/types";

/**
 * The one declaration of what a custom field may be, on this side.
 *
 * The union and the options rule were written out four times — the builder
 * and both of its forms had a copy each, next to the one in `types/core.ts`
 * that the rest of the app reads. They had already stopped agreeing: the
 * shared one carried a `uom_select` the backend has never accepted and
 * nothing ever produced, so a definition typed against it would have been
 * refused on save.
 *
 * Both halves mirror `app/schemas/category.py` — `FieldType` and
 * `_OPTIONS_REQUIRED_TYPES` — and a test holds them to it, because a
 * builder that offers a type the API rejects is a form that cannot be
 * submitted.
 */
export type { FieldType };

/** Types that require a non-empty `options` list. */
export const OPTIONS_REQUIRED_TYPES: ReadonlySet<FieldType> =
  new Set<FieldType>(["select", "multi-select"]);

/** Whether this type is one the reader has to list the choices for. */
export function needsOptions(type: FieldType): boolean {
  return OPTIONS_REQUIRED_TYPES.has(type);
}

/**
 * The definitions that are fields to a reader. One with no type is a module's
 * visibility flag for a built-in column: it has nothing to edit, and no
 * catalogue names it — so no list shows it and no count includes it.
 */
export function listedFields(
  fields: readonly FieldDefinition[],
): FieldDefinition[] {
  return fields.filter((f) => f.type && f.label && f.label.trim() !== "");
}
