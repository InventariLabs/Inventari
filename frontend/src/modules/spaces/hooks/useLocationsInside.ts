import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import type { StorageLocationSummary } from "@/types";

/** The longest text the search accepts (`q` on the locations list). */
const SEARCH_MAX = 100;
const PATH_SEPARATOR = " → ";

/**
 * How many locations stand inside this one, at any depth.
 *
 * A place with nothing directly under it has nothing inside, and says so
 * without a request. Otherwise the answer is the number of places whose path
 * runs through this one, read as the total of a one-row page — the count
 * without the rows, and without the subtree. Names are unique within a
 * parent, so a full path names one place and its prefix is the subtree. A
 * path longer than the search accepts falls back to the direct children, a
 * lower bound that is true as far as it goes.
 */
export function useLocationsInside(
  location: Pick<StorageLocationSummary, "full_path" | "direct_children_count">,
): number {
  const excludeModuleContexts = !useShowModuleData();
  const prefix = location.full_path
    ? `${location.full_path}${PATH_SEPARATOR}`
    : null;
  const askable =
    location.direct_children_count > 0 &&
    prefix !== null &&
    prefix.length <= SEARCH_MAX;
  const { data } = useQuery({
    queryKey: [
      ...queryKeys.storages.all,
      "inside",
      prefix,
      excludeModuleContexts,
    ],
    queryFn: () =>
      storagesApi.getPage({
        q: prefix ?? undefined,
        exclude_module_contexts: excludeModuleContexts || undefined,
        counts: false,
        limit: 1,
      }),
    enabled: askable,
  });
  if (location.direct_children_count === 0) return 0;
  return askable && data ? data.total : location.direct_children_count;
}
