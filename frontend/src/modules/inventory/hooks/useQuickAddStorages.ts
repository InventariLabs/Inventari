import { useLocationOffer } from "@/module-sdk";
import type { LocationScope } from "@/module-sdk";

/**
 * A stock flow's offer, not the general lists': the form puts goods down, so
 * what it hands out is what may hold stock — never a place a module owns,
 * whatever the organization mixes into its lists. A form that could name a
 * location only the Storages tab shows would create a record the reader then
 * cannot place, and one that could name a server rack would file a product
 * where goods do not go. The place the form arrived holding (`keepId`) is
 * still offered, so opening an existing record never silently clears where it
 * is — the form checks that itself.
 */
export const QUICK_ADD_STORAGE_SCOPE: LocationScope = { purpose: "stock" };

/**
 * Whether the quick-add form has anywhere to put a product, and why not.
 *
 * Asked of the endpoint as a count, not of a list: the form's picker searches
 * the places, so the page never holds them. "Hidden" means a location this
 * picker would offer and the policy is holding back — never a virtual
 * counterpart or an archived shelf, which no policy reveals. A stock flow
 * never gets that answer: its purpose keeps a module's places out whatever
 * the switch says, so the reason is "nothing to offer" and the way out the
 * form shows — create a location — is the one that works.
 */
export function useQuickAddStorages() {
  const offer = useLocationOffer(QUICK_ADD_STORAGE_SCOPE);
  return {
    /** `true` when there is no place at all; `undefined` while unknown. */
    noStorages: offer.total === undefined ? undefined : offer.total === 0,
    hasHidden: offer.emptyReason === "module-data-hidden",
    isError: offer.isError,
    refetch: offer.refetch,
  };
}
