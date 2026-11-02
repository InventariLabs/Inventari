import { useMemo } from "react";
import {
  useLocationOffer,
  useLocationsById,
  useOfferedLocations,
} from "@/module-sdk";
import { readLastUsedLocations } from "@/modules/warehouse/lib/lastUsedLocations";
import type { DocumentType } from "@/modules/warehouse/types";

/**
 * The places a document form works with, asked of the server one question at
 * a time instead of read from a list of every location: what a stock flow
 * offers (a count and the first two, enough to take the only one there is),
 * which of the places the form remembers from last time are still on offer,
 * and the name of the place the line search is limited to.
 *
 * The pickers search the places themselves; this is only what the form needs
 * to know before the reader opens one.
 */
export function useDocumentPlaces({
  isEdit,
  docType,
  stockLocationId,
}: {
  isEdit: boolean;
  docType: DocumentType;
  stockLocationId: string | null | undefined;
}) {
  const offer = useLocationOffer({ purpose: "stock" });
  const { byId: stockPlace } = useLocationsById([stockLocationId]);
  const remembered = useMemo(
    () => (isEdit ? undefined : readLastUsedLocations()[docType]),
    [isEdit, docType],
  );
  const rememberedOffered = useOfferedLocations(
    [remembered?.source, remembered?.target],
    { enabled: !isEdit },
  );
  const offeredIds = useMemo(() => {
    // A check that failed does not say the places are gone: the pair stays
    // remembered, and the server refuses a place that may not be used when
    // the document is saved.
    if (rememberedOffered.isError) {
      return new Set(
        [remembered?.source, remembered?.target].filter(
          (id): id is string => !!id,
        ),
      );
    }
    return new Set(rememberedOffered.data ?? []);
  }, [rememberedOffered.isError, rememberedOffered.data, remembered]);

  return {
    emptyReason: offer.emptyReason,
    offeredIds,
    locationsLoaded: offer.total !== undefined && !rememberedOffered.isLoading,
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
