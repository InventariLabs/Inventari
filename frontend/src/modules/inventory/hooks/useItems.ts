import { useInfiniteQuery } from "@tanstack/react-query";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { itemsApi } from "@/lib/api/items";
import type { Item, ItemAggregates, ItemListResponse } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";

export type ItemsParams = {
  location_id?: string;
  category_id?: string;
  context_tag?: string;
  exclude_module_contexts?: boolean;
  search?: string;
  expiring_days?: number;
  only_expired?: boolean;
  only_low_stock?: boolean;
  needs_attention?: boolean;
  /**
   * Also return records with nothing left, wherever they sit. Consuming the
   * last unit files one under the virtual Consumed location, which the
   * internal-usage default hides; the "show used up" chip asks for them
   * without the reader naming a location.
   */
  include_empty?: boolean;
  offset?: number;
  limit?: number;
  sort_by?: "created_at" | "name" | "quantity" | "expiry_date";
  sort_order?: "asc" | "desc";
  /**
   * Comma-separated product template ids. Neutral on purpose — modules supply
   * the set (e.g. "the templates that have a formula") and the list narrows
   * to it without Core learning what the set means.
   */
  template_ids?: string;
};

/**
 * Fetch items with optional filtering.
 * When params are passed, they are included in the query key so each
 * unique filter combination has its own cache entry.
 * Invalidating `queryKeys.items.all` = ['items'] will invalidate ALL items queries (prefix match).
 */
export function useItems(
  params?: ItemsParams,
  paginated = false,
  options?: { enabled?: boolean },
) {
  return useQuery<ItemListResponse>({
    queryKey: params ? [...queryKeys.items.all, params] : queryKeys.items.all,
    queryFn: () => itemsApi.getAll(params),
    placeholderData: paginated ? keepPreviousData : undefined,
    enabled: options?.enabled ?? true,
  });
}

export type ItemAggregatesParams = Omit<
  ItemsParams,
  "offset" | "limit" | "sort_by" | "sort_order"
>;

/**
 * Totals over the whole filtered set. The list paginates, so its
 * footer sums come from this query, keyed on the same filters minus the
 * paging — the footer and the rows read one cache family (`items`), so a
 * mutation that invalidates the list invalidates the sums with it.
 */
export function useItemAggregates(
  params?: ItemAggregatesParams,
  options?: { enabled?: boolean },
) {
  return useQuery<ItemAggregates>({
    queryKey: [...queryKeys.items.all, "aggregates", params ?? {}],
    queryFn: () => itemsApi.getAggregates(params),
    placeholderData: keepPreviousData,
    enabled: options?.enabled ?? true,
  });
}

/**
 * How many rows the module filter keeps off the list — 0 until a probe says
 * more. An empty *filtered* answer can mean "nothing is here" or "it belongs
 * to a switched-off module", and the list cannot tell by looking at zero; a
 * *populated* one hides the same fact behind its own rows. One one-row query
 * without the module filter answers it — it runs beside the list for as long
 * as the reader has not narrowed the list themselves, and the counter is the
 * difference between what exists and what this list shows.
 */
export function useHiddenItemCount(
  excludeModuleContexts: boolean,
  isLoading: boolean,
  total: number | undefined,
  isNarrowed: boolean,
): number {
  const shouldProbe = excludeModuleContexts && !isLoading && !isNarrowed;
  const { data, isError } = useItems(
    { exclude_module_contexts: false, limit: 1 },
    true,
    { enabled: shouldProbe },
  );
  // While the reader narrows the list themselves the counter steps aside:
  // a stale probe answer must not speak over the filtering they are doing.
  // So does a probe that failed: it has no count to give, and the list under
  // it speaks for itself when its own request fails.
  if (!shouldProbe || isError) return 0;
  // A count not known to its end (`total` undefined: the list stopped
  // counting and the footer has not answered yet) or a probe that stopped at
  // the cap has no difference to tell; the counter steps aside instead of
  // claiming nothing is hidden.
  if (total === undefined || data?.total_capped) return 0;
  const unfilteredTotal = data?.total ?? 0;
  return Math.max(unfilteredTotal - total, 0);
}

export function useItem(itemId: string) {
  return useQuery<Item>({
    queryKey: queryKeys.items.detail(itemId),
    queryFn: () => itemsApi.getById(itemId),
    enabled: !!itemId,
  });
}

/**
 * Search the organization's products.
 *
 * `storageId` narrows the search to one place before the page is cut. The
 * page is ordered by creation across the whole organization, so a shelf that
 * holds a matching record can fall off it entirely behind a hundred matches
 * elsewhere; a screen that means "this place first" asks about the place
 * separately instead of reordering the organization's page.
 */
export function useItemSearch(query: string, storageId?: string) {
  return useQuery<ItemListResponse>({
    queryKey: queryKeys.items.search(query, storageId),
    queryFn: () =>
      itemsApi.getAll({
        search: query,
        ...(storageId ? { location_id: storageId } : {}),
      }),
    enabled: query.length > 0,
  });
}

export function useArchivedItems(params?: {
  offset?: number;
  limit?: number;
  search?: string;
  /** The organization policy, applied to the archive as to the active list. */
  exclude_module_contexts?: boolean;
}) {
  return useQuery({
    queryKey: params
      ? [...queryKeys.items.archived, params]
      : queryKeys.items.archived,
    queryFn: () => itemsApi.getArchived(params),
    placeholderData: params ? keepPreviousData : undefined,
  });
}

export function useItemDetailHistory(itemId: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.items.itemHistory(itemId),
    queryFn: ({ pageParam }) => itemsApi.getItemHistory(itemId, 50, pageParam),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    initialPageParam: undefined as string | undefined,
    enabled: !!itemId,
  });
}
