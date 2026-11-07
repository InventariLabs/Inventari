import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import type { StoragePageParams } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import { locationScopeParams } from "@/module-sdk";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import type { StorageLocationSummary } from "@/types";

/** Names the suggestions are checked against; more than this is not a list
 *  anyone compares chips with. */
const NAMES_PAGE = 200;

/**
 * Every place standing at a level, whoever it belongs to. A name is unique
 * among its siblings across the whole organization — a module's own places
 * and archived ones count too — so the list's scope is the wrong filter for
 * names: with module data hidden, the equipment module's "Server Room" was
 * offered as a chip, and the server refused it as taken, or, as a first step
 * with a place inside it, hung the new place in the module's room.
 */
const EVERY_PLACE: StoragePageParams = {
  usage: "all",
  include_archived: true,
  counts: false,
};

/**
 * The names a new location must not repeat as a suggestion: the top level and
 * the places directly under the chosen parent. The wizard's chips are checked
 * against these two small levels, not against every location there is.
 *
 * `topLevelTotal` is how many places stand at the top of the list the wizard
 * was opened from; with the offered total it says whether the organization
 * has any structure beyond them.
 */
export function useExistingLocations(parentId?: string | null) {
  const showModuleData = useShowModuleData();
  const scope = locationScopeParams({}, showModuleData);
  const top = useQuery({
    queryKey: [...queryKeys.storages.all, "existing", "top", scope],
    queryFn: () => storagesApi.getPage({ ...scope, top_level: true, limit: 1 }),
  });
  const topNames = useQuery({
    queryKey: [...queryKeys.storages.all, "existing", "top-names"],
    queryFn: () =>
      storagesApi.getPage({
        ...EVERY_PLACE,
        top_level: true,
        limit: NAMES_PAGE,
      }),
  });
  const below = useQuery({
    queryKey: [...queryKeys.storages.all, "existing", "below", parentId],
    queryFn: () =>
      storagesApi.getPage({
        ...EVERY_PLACE,
        parent_id: parentId ?? undefined,
        limit: NAMES_PAGE,
      }),
    enabled: !!parentId,
  });
  const rows: StorageLocationSummary[] = [
    ...(topNames.data?.items ?? []),
    ...(below.data?.items ?? []),
  ];
  return {
    rows,
    topLevelTotal: top.data?.total,
    // Either level failing leaves the names to check against short: the
    // suggestions would offer a name that stands there already.
    isError: top.isError || topNames.isError || below.isError,
    error: top.error ?? topNames.error ?? below.error,
    refetch: () => {
      void top.refetch();
      void topNames.refetch();
      if (parentId) void below.refetch();
    },
  };
}
