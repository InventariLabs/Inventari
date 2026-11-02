import { useMemo } from "react";
import { useLocationsById } from "@/module-sdk";

/**
 * A location's name, resolved by id.
 *
 * The detail payload carries `location_id` and no name, so the card
 * that has to answer "where is it" looks the name up by id — the places the
 * screen shows (`ids`), never the organization's whole list. Rows the lookup
 * does not know keep the name the API sent.
 *
 * This used to translate the name as well: a seeded location was written to
 * the database in English and read by people working in five languages. It is
 * written in the reader's language now — see
 * `StorageLocationDeclaration.translations` — so there is nothing left to
 * translate here, and the path under a picker, the printed label and every
 * exported document agree with the screen instead of contradicting it.
 */
export function useLocationLabel(
  ids: ReadonlyArray<string | null | undefined>,
): (
  locationId: string | null | undefined,
  rawName: string | null | undefined,
) => string | null {
  // Naming, not offering: a row that already stands somewhere has to be able
  // to say where, even when the location belongs to another module or is a
  // virtual counterpart. `usage: "all"` is the list that reaches them; the
  // pickers on this module's screens take a narrower one on purpose.
  //
  // Rows the list cannot name keep the name the API sent, and so does every
  // row while the list is missing or failed: nothing is claimed either way.
  const { byId } = useLocationsById(ids);

  const nameById = useMemo(
    () => new Map([...byId].map(([id, place]) => [id, place.name])),
    [byId],
  );

  return useMemo(
    () => (locationId, rawName) =>
      (locationId ? nameById.get(locationId) : undefined) ?? rawName ?? null,
    [nameById],
  );
}
