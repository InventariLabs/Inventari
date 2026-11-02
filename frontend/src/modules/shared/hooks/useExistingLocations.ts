import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import { locationScopeParams } from "@/module-sdk";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import type { StorageLocationSummary } from "@/types";

/** Names the suggestions are checked against; more than this is not a list
 *  anyone compares chips with. */
const NAMES_PAGE = 200;

/**
 * The names a new location must not repeat as a suggestion: the top level and
 * the places directly under the chosen parent. The wizard's chips are checked
 * against these two small levels, not against every location there is.
 *
 * `topLevelTotal` is how many places stand at the top; with the offered total
 * it says whether the organization has any structure beyond them.
 */
export function useExistingLocations(parentId?: string | null) {
  const showModuleData = useShowModuleData();
  const scope = locationScopeParams({}, showModuleData);
  const top = useQuery({
    queryKey: [...queryKeys.storages.all, "existing", "top", scope],
    queryFn: () =>
      storagesApi.getPage({ ...scope, top_level: true, limit: NAMES_PAGE }),
  });
  const below = useQuery({
    queryKey: [...queryKeys.storages.all, "existing", "below", parentId, scope],
    queryFn: () =>
      storagesApi.getPage({
        ...scope,
        parent_id: parentId ?? undefined,
        limit: NAMES_PAGE,
      }),
    enabled: !!parentId,
  });
  const rows: StorageLocationSummary[] = [
    ...(top.data?.items ?? []),
    ...(below.data?.items ?? []),
  ];
  return {
    rows,
    topLevelTotal: top.data?.total,
    // Either level failing leaves the names to check against short: the
    // suggestions would offer a name that stands there already.
    isError: top.isError || below.isError,
    error: top.error ?? below.error,
    refetch: () => {
      void top.refetch();
      if (parentId) void below.refetch();
    },
  };
}
