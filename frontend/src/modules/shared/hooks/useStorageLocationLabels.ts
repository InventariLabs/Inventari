import { useMemo } from "react";
import { useLocationsById } from "@/module-sdk";
import { getStorageLocationPath } from "@/utils/helpers";

/**
 * Names a place the way the pickers above the list do: by its path.
 *
 * A stock or ledger row arrives with the location's bare name, and two
 * shelves called "Shelf 1" under different warehouses then read as one place
 * — while the filter directly above says "Warehouse A → Aisle 1 → Shelf 1".
 * The places are looked up by id — only the ids the caller shows, never the
 * organization's catalogue (archived locations included: a row can stand on a
 * shelf that has since been put away); a row whose place cannot be named
 * keeps the name it came with, and so does every row until the answer has
 * arrived.
 */
export function useStorageLocationLabels(
  ids: ReadonlyArray<string | null | undefined>,
): (
  id: string | null | undefined,
  fallbackName: string | null | undefined,
) => string | null {
  const { byId } = useLocationsById(ids);

  return useMemo(
    () => (id, fallbackName) => {
      const location = id ? byId.get(id) : undefined;
      return location
        ? getStorageLocationPath(location)
        : (fallbackName ?? null);
    },
    [byId],
  );
}
