import type { Item } from "@/types";

/**
 * Whether the register lists this record: filed under a category carrying the
 * equipment context tag, or — under no category — holding the module's
 * namespace in its metadata.
 *
 * The mirror of the backend's ownership predicate, in its order: the category
 * speaks first, so a record filed under an ordinary category is an ordinary
 * record whatever its metadata carries. Under no category the namespace's
 * *presence* is the answer, not its value: `{"equipment": null}` is a
 * namespace the register lists, because a JSON null is not SQL NULL.
 *
 * The assets' own page, the product list's quick actions and the product's
 * own page all ask it, and the answer decides both whether the record opens
 * as an asset and which verbs it is offered.
 */
export function isEquipmentRecord(item: Item): boolean {
  if (item.category) return item.category.context_tag === "equipment";
  return item.metadata?.equipment !== undefined;
}
