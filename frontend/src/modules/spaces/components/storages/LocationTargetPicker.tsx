import { useState } from "react";
import {
  SearchableCombobox,
  type SearchableComboboxProps,
} from "@/components/ui/SearchableCombobox";
import {
  LocationSearchFailed,
  useLocationSearch,
  useLocationsById,
  type LocationScope,
} from "@/module-sdk";
import { locationOption } from "@/module-sdk";
import { useDebounce } from "@/module-sdk";
import { isVirtualUsage } from "@/modules/shared/lib/storageUsage";
import type { StorageLocationSummary } from "@/types";
import { LOCATION_PATH_SEPARATOR } from "@/utils/helpers";

/** Rows one lookup returns; the exclusions are applied to them afterwards. */
const TARGET_PAGE_SIZE = 100;

type LocationTargetPickerProps = Omit<
  SearchableComboboxProps,
  "options" | "loading" | "onSearchChange"
> & {
  scope?: LocationScope;
  /** Places that cannot be chosen, nor anything standing inside them: the
   *  place being moved or archived and its whole subtree. */
  excludeSubtreeOf?: readonly string[];
  /** Only places with nothing standing inside them. */
  leavesOnly?: boolean;
};

/** Whether `path` is `inside` or a place below it. Names are unique within a
 *  parent, so a full path names one place and the prefix is the subtree. */
export function isInsidePath(path: string | null | undefined, inside: string) {
  return (
    !!path &&
    (path === inside || path.startsWith(`${inside}${LOCATION_PATH_SEPARATOR}`))
  );
}

/**
 * A destination for a location or its records: searched on the server, with
 * the places that cannot be one left out.
 *
 * The server answers for what was typed; the place being moved and what stands
 * inside it are taken out of that answer by path, so the picker never offers a
 * destination the move would be refused for, and never loads the tree to know
 * which ones those are. Virtual counterparts are never offered.
 */
export function LocationTargetPicker({
  scope = {},
  excludeSubtreeOf = [],
  leavesOnly = false,
  value,
  ...rest
}: LocationTargetPickerProps) {
  const [search, setSearch] = useState("");
  const typed = search.trim();
  const debounced = useDebounce(typed, 300);
  const list = useLocationSearch(scope, debounced, {
    limit: TARGET_PAGE_SIZE,
  });
  const excluded = useLocationsById(excludeSubtreeOf);
  const chosen = useLocationsById(value ? [value] : []);

  const excludedPaths = excludeSubtreeOf.map(
    (id) => excluded.byId.get(id)?.full_path ?? "",
  );
  const offered = (row: StorageLocationSummary) =>
    !excludeSubtreeOf.includes(row.id) &&
    !isVirtualUsage(row.usage) &&
    (!leavesOnly || row.is_leaf) &&
    !excludedPaths.some((path) => path && isInsidePath(row.full_path, path));

  // The exclusions are read from the places being moved: without them the
  // picker would offer destinations the move is refused for, so a failed read
  // of either is a failed search, not a shorter list.
  const failed = list.isError || excluded.isError;
  const rows = failed ? [] : (list.data?.items ?? []).filter(offered);
  const options = rows.map(locationOption);
  const held = chosen.byId.get(value ?? "");
  // The chosen place leads the list while nothing is typed, so the field can
  // name it even when it is not on this page.
  if (held && !typed && !rows.some((row) => row.id === held.id)) {
    options.unshift(locationOption(held));
  }

  return (
    <SearchableCombobox
      {...rest}
      value={value}
      options={options}
      loading={list.isLoading || typed !== debounced}
      onSearchChange={setSearch}
      emptyMessage={
        failed ? (
          <LocationSearchFailed
            onRetry={() => {
              void list.refetch();
              void excluded.refetch();
            }}
          />
        ) : (
          rest.emptyMessage
        )
      }
    />
  );
}
