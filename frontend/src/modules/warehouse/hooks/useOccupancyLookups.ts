import { useMemo } from "react";
import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { useDebounce } from "@/hooks/useDebounce";
import { stockQuantsApi, type StockQuantRow } from "@/module-sdk";
import { putawayOccupancyApi } from "@/modules/warehouse/api/putaway";
import type {
  OccupancyEntry,
  OccupancyHit,
} from "@/modules/warehouse/components/occupancy/occupancyModel";

/** The most stock rows a "where is…" search reads; past it the reader types more. */
export const SEARCH_LIMIT = 500;

/** A read that did not answer, and how to ask it again. */
export interface LookupFailure {
  error: unknown;
  retry: () => void;
}

export interface ShelfEntries {
  /** Every product of each opened shelf whose read has answered. */
  entries: Map<string, OccupancyEntry[]>;
  /** The opened shelves whose read failed: no products is not an empty shelf. */
  failures: Map<string, LookupFailure>;
}

/**
 * Every product of the shelves the reader opened.
 *
 * The overview of the floor carries each shelf's fill and a count of what
 * stands there, not the products themselves — a hundred thousand products
 * on two thousand shelves made it tens of megabytes. A shelf opened in the
 * tree, or picked on the map, is read on its own, through the same per-location
 * read the receive screen uses. A shelf that is both opened and picked is
 * one read, not two observers of the same query.
 */
export function useShelfEntries(requestedIds: string[]): ShelfEntries {
  const locationIds = [...new Set(requestedIds)];
  const queries = useQueries({
    queries: locationIds.map((locationId) => ({
      queryKey: queryKeys.documents.putawayOccupancy(locationId),
      queryFn: () => putawayOccupancyApi.get(locationId),
      staleTime: 60_000,
    })),
  });
  const entries = new Map<string, OccupancyEntry[]>();
  const failures = new Map<string, LookupFailure>();
  locationIds.forEach((locationId, index) => {
    const query = queries[index];
    if (query?.isError) {
      failures.set(locationId, {
        error: query.error,
        retry: () => void query.refetch(),
      });
      return;
    }
    const cell = query?.data?.locations.find(
      (location) => location.location_id === locationId,
    );
    if (cell) entries.set(locationId, cell.entries);
  });
  return { entries, failures };
}

export interface OccupancyHits {
  /** What the search found, per shelf; null while nothing is searched. */
  byLocation: Map<string, OccupancyHit[]> | null;
  /** More shelves matched than the search marks. */
  truncated: boolean;
  /** The search did not answer: the floor it did not filter is no answer. */
  failure: LookupFailure | null;
}

/**
 * Where the products the reader typed lie: the stock list's own search —
 * name, brand, barcode, SKU or batch — summed per shelf and product.
 *
 * Asked of the server because the floor's overview no longer carries every
 * product of every shelf. The answer of the previous word stays on screen
 * while the next one is read, so the tree does not fall back to the whole
 * floor between two keystrokes.
 */
export function useOccupancyHits(needle: string): OccupancyHits {
  const search = useDebounce(needle.trim(), 250);
  const filters = { search, limit: SEARCH_LIMIT };
  const { data, isError, error, refetch } = useQuery({
    queryKey: queryKeys.stockQuants.list(filters),
    queryFn: () => stockQuantsApi.list(filters),
    enabled: search.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
  // One map per answer: the screen filters the whole floor by it.
  const byLocation = useMemo(() => (data ? toHits(data.items) : null), [data]);
  if (!needle.trim())
    return { byLocation: null, truncated: false, failure: null };
  if (isError)
    return {
      byLocation: null,
      truncated: false,
      failure: { error, retry: () => void refetch() },
    };
  if (!byLocation) return { byLocation: null, truncated: false, failure: null };
  return { byLocation, truncated: Boolean(data?.has_more), failure: null };
}

/** The stock list's rows summed per shelf and product. */
function toHits(rows: StockQuantRow[]): Map<string, OccupancyHit[]> {
  const byLocation = new Map<string, OccupancyHit[]>();
  for (const row of rows) {
    const hits = byLocation.get(row.location_id) ?? [];
    const same = hits.find((hit) => hit.productId === row.product_template_id);
    if (same) {
      same.quantity = String(Number(same.quantity) + Number(row.quantity));
    } else {
      hits.push({
        productId: row.product_template_id,
        name: row.product_name ?? "",
        quantity: row.quantity,
        unit: row.uom_symbol ?? null,
      });
    }
    byLocation.set(row.location_id, hits);
  }
  return byLocation;
}
