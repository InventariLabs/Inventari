import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import {
  locationScopeParams,
  useLocationOffer,
  type LocationScope,
} from "@/module-sdk";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";

/**
 * What a product form's location field offers, answered without reading the
 * organization's locations: whether one place is all there is (the form puts
 * it in the field), and whether the place the field holds is one the picker
 * would offer (a remembered pick may be gone, archived or a module's).
 *
 * `scope` undefined is a form that checks nothing — an existing product keeps
 * its own place whether or not it would be offered today. `keepId` is a place
 * the form arrived holding: it stays offered whatever the scope says, for as
 * long as it exists.
 */
export function useStorageOffer(
  scope: LocationScope | undefined,
  chosenId: string,
  keepId?: string | null,
) {
  const showModuleData = useShowModuleData();
  const offer = useLocationOffer(scope ?? {}, { enabled: !!scope });
  const kept = !!chosenId && chosenId === keepId;
  const asked = scope
    ? {
        ...locationScopeParams(scope, showModuleData),
        ids: [chosenId],
        limit: 1,
      }
    : undefined;
  const check = useQuery({
    queryKey: [...queryKeys.storages.all, "offered", asked],
    queryFn: () => storagesApi.getPage(asked!),
    enabled: !!scope && !!chosenId && !kept,
  });

  // A place the form arrived holding is offered whatever the scope says, but
  // it still has to exist: one removed while the context was held would show
  // an empty-looking field the form could not save into.
  const exists = useQuery({
    queryKey: [...queryKeys.storages.all, "exists", chosenId],
    queryFn: () => storagesApi.getPage({ ids: [chosenId], limit: 1 }),
    enabled: !!scope && kept,
  });

  let chosenOffered: boolean | undefined;
  if (scope && chosenId) {
    if (kept) chosenOffered = exists.data ? exists.data.total > 0 : true;
    else if (check.data) chosenOffered = check.data.total > 0;
  }
  return {
    /** The offer itself: its size, its first rows, why it is empty. */
    offer,
    /** The one place on offer, when there is exactly one; `undefined` while
     *  the offer has not answered. */
    soleId:
      offer.total === undefined
        ? undefined
        : offer.total === 1
          ? (offer.first[0]?.id ?? null)
          : null,
    /** Whether the field's current value is offered; `undefined` when
     *  nothing is chosen, nothing is checked, or the answer is on its way. */
    chosenOffered,
  };
}
