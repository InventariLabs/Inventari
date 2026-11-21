import { useMemo } from "react";
import { useLocationOffer, useLocationsById } from "@/module-sdk";

/**
 * The places a document form works with, asked of the server one question at
 * a time instead of read from a list of every location: what a stock flow
 * offers (a count and the first two, enough to take the only one there is),
 * and the name of the place the line search is limited to.
 *
 * The pickers search the places themselves; this is only what the form needs
 * to know before the reader opens one.
 */
export function useDocumentPlaces({
  stockLocationId,
}: {
  stockLocationId: string | null | undefined;
}) {
  const offer = useLocationOffer({ purpose: "stock" });
  const { byId: stockPlace } = useLocationsById([stockLocationId]);
  return {
    emptyReason: offer.emptyReason,
    locationsLoaded: offer.total !== undefined,
    onlyLocationId: offer.total === 1 ? (offer.first[0]?.id ?? null) : null,
    stockPlaceName: stockPlace.get(stockLocationId ?? "")?.name,
  };
}

/** The two places a document stands between, named by id for its grid. */
export function useDocumentPlaceNames(
  doc:
    | { source_location_id?: string | null; target_location_id?: string | null }
    | undefined,
) {
  const { byId } = useLocationsById([
    doc?.source_location_id,
    doc?.target_location_id,
  ]);
  return useMemo(() => [...byId.values()], [byId]);
}
