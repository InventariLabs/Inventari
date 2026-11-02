import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import {
  locationScopeParams,
  useLocationsById,
  type LocationScope,
} from "@/hooks/queries/useLocations";
import { useDebounce } from "@/hooks/useDebounce";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import type { StorageLocationSummary } from "@/types";

/** Rows one lookup returns — enough to read, the search narrows the rest. */
const PICKER_PAGE_SIZE = 30;
const SEARCH_DEBOUNCE_MS = 300;
const PATH_SEPARATOR = " → ";
const PARENT_SEPARATOR = " › ";

export interface LocationOption {
  id: string;
  /** The place's own name, whole — the title of its row. */
  name: string;
  /** The places above it, the caption under the name. */
  path?: string;
  /** The icon of the place's type, when it has one. */
  icon?: string;
  /** The module context the place carries — a picker that mixes module
   *  places says whose one is (`LocationCombobox` turns it into a badge). */
  contextTag?: string | null;
}

/** A place as a picker row: its own name first, the way to it as the caption. */
export function locationOption(
  location: Pick<StorageLocationSummary, "id" | "name" | "full_path"> &
    Partial<Pick<StorageLocationSummary, "location_type" | "context_tag">>,
): LocationOption {
  const parts = (location.full_path ?? "").split(PATH_SEPARATOR);
  const above = parts.length > 1 ? parts.slice(0, -1) : [];
  return {
    id: location.id,
    name: location.name,
    path: above.length > 0 ? above.join(PARENT_SEPARATOR) : undefined,
    icon: location.location_type?.icon || undefined,
    contextTag: location.context_tag,
  };
}

/**
 * The location field of a form: the places a scope offers, looked up on the
 * server by name, code or path as the reader types. The list is one page,
 * never the catalogue, so an organization with two thousand shelves finds the
 * last of them the same way as the first.
 *
 * A place already chosen may not be on that page; it is read on its own so the
 * field can name it. `keepId` places stay selectable whatever the scope says
 * (opening a record never blanks the place it stands in).
 */
export function useLocationPicker(
  scope: LocationScope,
  selectedId?: string | null,
  options?: { enabled?: boolean },
) {
  const showModuleData = useShowModuleData();
  const [search, setSearch] = useState("");
  const typed = search.trim();
  const debounced = useDebounce(typed, SEARCH_DEBOUNCE_MS);
  const params = {
    ...locationScopeParams(scope, showModuleData),
    q: debounced || undefined,
    limit: PICKER_PAGE_SIZE,
  };
  const list = useQuery({
    queryKey: [...queryKeys.storages.all, "picker", params],
    queryFn: () => storagesApi.getPage(params),
    enabled: options?.enabled ?? true,
    placeholderData: keepPreviousData,
  });
  const listed = list.data?.items;
  const onPage = listed?.some((row) => row.id === selectedId) ?? false;
  const named = useLocationsById(!selectedId || onPage ? [] : [selectedId]);
  const selected = named.byId.get(selectedId ?? "");

  const rows: LocationOption[] = (listed ?? []).map(locationOption);
  // The chosen place leads the list while nothing is typed, so the field can
  // name it. Under a typed query it would be an answer to nothing.
  const pinned =
    !onPage && !search && selected ? [locationOption(selected)] : [];

  return {
    options: [...pinned, ...rows],
    setSearch,
    // Typed text the server has not been asked about yet is also "on its
    // way": the rows on screen answer the previous query.
    loading: list.isLoading || typed !== debounced,
    /** Set only when the read failed — a failed list says nothing about
     *  whether there are places. */
    error: list.isError ? list.error : null,
    retry: () => void list.refetch(),
    /** How many places match in all; `undefined` until the list answers. */
    total: list.data?.total,
  };
}
