import { getStorageLocationPath, type LocationPathNode } from "./helpers";

/**
 * A location as a picker row: the place's own name as the title and the
 * path that places it as the caption — the arrangement the other location
 * pickers already use.
 *
 * A row that carried the whole path as its title lost the end first when a
 * phone clipped it, and the end is the only part that tells "Main Warehouse
 * → Cold Storage → Fridge A" from "… → Freezer Zone". The caption can lose
 * its tail without costing the choice anything, and the picker's search
 * still matches it. The path is rebuilt from `allStorages` when the record
 * carries none of its own.
 */
export function storageLeafOption(
  storage: LocationPathNode & { id: string },
  allStorages?: readonly LocationPathNode[],
): { id: string; name: string; path?: string } {
  const path = getStorageLocationPath(storage, undefined, {}, allStorages);
  return {
    id: storage.id,
    name: storage.name,
    path: path && path !== storage.name ? path : undefined,
  };
}

/**
 * The same row on one line, for a control with no room for a caption — a
 * native `<option>`, a table cell: the name first, so whatever the width
 * clips is the path behind it, never the place itself.
 */
export function storageLeafLabel(row: { name: string; path?: string }): string {
  return row.path ? `${row.name} — ${row.path}` : row.name;
}
