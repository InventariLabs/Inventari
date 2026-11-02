import { useMemo } from "react";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import { storagesApi, type StoragePageParams } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import type { StorageLocationSummary } from "@/types";
import type {
  LocationPickerEmptyReason,
  LocationPickerPurpose,
} from "@/modules/shared/lib/locationPickerOffer";

/**
 * Where a screen reads its places from, in the words of the flow behind it.
 *
 * A screen never reads the organization's locations whole: it searches them,
 * names the ones its rows stand in, or opens one branch of the tree. What it
 * may *offer* is still decided here, in one place, so every picker answers
 * the same question the same way.
 */
export interface LocationScope {
  /** `stock` offers what may hold goods; `general` follows the organization's
   *  module-data policy (`LocationPickerPurpose`). Default `general`. */
  purpose?: LocationPickerPurpose;
  /** One vertical module's own places (tagged for it, or holding its records). */
  moduleScope?: string;
  /** Places tagged for one module (`__none__`: the untagged ones). */
  contextTag?: string;
  /** `all` reaches the virtual counterparts; the default is internal places. */
  usage?: string;
  /** Archived places too — for a screen that names where records stood. */
  includeArchived?: boolean;
}

/** The endpoint's ask for a scope, once the organization's policy is known. */
export function locationScopeParams(
  scope: LocationScope,
  showModuleData: boolean,
): StoragePageParams {
  const params: StoragePageParams = { counts: false };
  if (scope.moduleScope) params.module_scope = scope.moduleScope;
  else if (scope.contextTag) params.context_tag = scope.contextTag;
  else if ((scope.purpose ?? "general") === "stock" || !showModuleData) {
    // A stock flow excludes a module's own places whatever the organization
    // says its lists should mix; a general screen follows the policy.
    params.exclude_module_contexts = true;
  }
  if (scope.usage) params.usage = scope.usage;
  if (scope.includeArchived) params.include_archived = true;
  return params;
}

/** The most ids one request names (the endpoint's own cap is 200). */
const NAMING_CHUNK = 100;

type Id = string | null | undefined;

/**
 * The places a screen's rows stand in, named by id.
 *
 * Archived and virtual places come along: a record already on screen has to
 * be able to say where it is, even when the place has since been put away or
 * is a counterpart no picker offers. One request per hundred ids, only the
 * ids the screen holds — never the catalogue to look them up in.
 */
export function useLocationsById(
  ids: ReadonlyArray<Id>,
  options?: { enabled?: boolean },
) {
  // The ids as one string: the array is new on every render, its content is
  // the identity.
  const key = [...new Set(ids.filter((id): id is string => !!id))]
    .sort()
    .join(",");
  const wanted = useMemo(() => (key ? key.split(",") : []), [key]);
  const query = useQuery<StorageLocationSummary[]>({
    queryKey: [...queryKeys.storages.all, "named", key],
    queryFn: async () => {
      const chunks: string[][] = [];
      for (let i = 0; i < wanted.length; i += NAMING_CHUNK) {
        chunks.push(wanted.slice(i, i + NAMING_CHUNK));
      }
      const pages = await Promise.all(
        chunks.map((chunk) =>
          storagesApi.getPage({
            ids: chunk,
            usage: "all",
            include_archived: true,
            counts: false,
            limit: NAMING_CHUNK,
          }),
        ),
      );
      return pages.flatMap((page) => page.items);
    },
    enabled: (options?.enabled ?? true) && wanted.length > 0,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
  const byId = useMemo(
    () =>
      new Map((query.data ?? []).map((location) => [location.id, location])),
    [query.data],
  );
  return {
    byId,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * Which of these places a stock flow may use.
 *
 * A form that remembers the places it was last given asks whether they are
 * still on offer — by id, from the same scope the pickers search — instead of
 * reading the organization's locations to look them up, or taking a place's
 * name as proof that it may still receive goods.
 */
export function useOfferedLocations(
  ids: ReadonlyArray<string | null | undefined>,
  options?: { enabled?: boolean },
) {
  const showModuleData = useShowModuleData();
  const wanted = [...new Set(ids.filter((id): id is string => !!id))].sort();
  return useQuery({
    queryKey: [...queryKeys.storages.all, "offered", wanted.join(",")],
    queryFn: async () =>
      (
        await storagesApi.getPage({
          ...locationScopeParams({ purpose: "stock" }, showModuleData),
          ids: wanted,
          limit: Math.max(wanted.length, 1),
        })
      ).items.map((place) => place.id),
    enabled: (options?.enabled ?? true) && wanted.length > 0,
  });
}

/** One page of the places a scope offers, narrowed by what was typed. */
export function useLocationSearch(
  scope: LocationScope,
  search: string,
  options?: { limit?: number; enabled?: boolean },
) {
  const showModuleData = useShowModuleData();
  const params = {
    ...locationScopeParams(scope, showModuleData),
    q: search || undefined,
    limit: options?.limit ?? 30,
  };
  return useQuery({
    queryKey: [...queryKeys.storages.all, "search", params],
    queryFn: () => storagesApi.getPage(params),
    enabled: options?.enabled ?? true,
    placeholderData: keepPreviousData,
  });
}

/**
 * The places a scope offers, a page at a time, for a screen that lists them
 * as rows (a picker uses `useLocationSearch`). The search is answered by the
 * server; the record counts are asked for only when the rows print them.
 */
export function useLocationPages(
  scope: LocationScope,
  options: { search?: string; counts?: boolean; limit?: number } = {},
) {
  const showModuleData = useShowModuleData();
  const params = {
    ...locationScopeParams(scope, showModuleData),
    counts: options.counts ?? false,
    q: options.search || undefined,
    limit: options.limit ?? 50,
  };
  return useInfiniteQuery({
    queryKey: [...queryKeys.storages.all, "pages", params],
    queryFn: ({ pageParam }) =>
      storagesApi.getPage({ ...params, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.has_more ? last.offset + last.items.length : undefined,
    placeholderData: keepPreviousData,
  });
}

/**
 * What a scope has to offer, without reading it: how many places there are,
 * the first two, and — when there are none — why.
 *
 * A flow that needs only to know whether there is a place to put goods
 * ("add a location first"), or that defaults to the one place there is,
 * asks this instead of listing the organization.
 */
export function useLocationOffer(
  scope: LocationScope = {},
  options?: { enabled?: boolean },
) {
  const showModuleData = useShowModuleData();
  const params = {
    ...locationScopeParams(scope, showModuleData),
    limit: 2,
  };
  const offered = useQuery({
    queryKey: [...queryKeys.storages.all, "offer", params],
    queryFn: () => storagesApi.getPage(params),
    enabled: options?.enabled ?? true,
  });
  const purpose = scope.purpose ?? "general";
  const nothingOffered = offered.data !== undefined && offered.data.total === 0;
  // Places the policy keeps out of a general list: the same ask without the
  // exclusion. A stock flow keeps module places out on its own purpose, so
  // the setting would reveal nothing there — it never advises the switch.
  const needsProbe =
    nothingOffered &&
    purpose === "general" &&
    !showModuleData &&
    !scope.moduleScope &&
    !scope.contextTag;
  const hidden = useQuery({
    queryKey: [...queryKeys.storages.all, "offer-hidden", scope.usage ?? ""],
    queryFn: () =>
      storagesApi.getPage({
        usage: scope.usage,
        include_archived: scope.includeArchived || undefined,
        counts: false,
        limit: 1,
      }),
    enabled: needsProbe,
  });

  let emptyReason: LocationPickerEmptyReason | null = null;
  if (nothingOffered) {
    if (!needsProbe) emptyReason = "nothing-to-offer";
    else if (hidden.data !== undefined) {
      emptyReason =
        hidden.data.total > 0 ? "module-data-hidden" : "nothing-to-offer";
    }
  }
  return {
    /** How many places the scope offers; `undefined` until it answers. */
    total: offered.data?.total,
    /** The first two, enough to default to the only one there is. */
    first: offered.data?.items ?? [],
    emptyReason,
    isLoading: offered.isLoading,
    isError: offered.isError,
    error: offered.error,
    refetch: () => void offered.refetch(),
  };
}
