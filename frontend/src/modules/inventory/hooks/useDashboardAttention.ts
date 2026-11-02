import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Item, LowStockProduct, StorageLocationNode } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";
import { storagesApi } from "@/lib/api/storages";
import { itemsApi } from "@/lib/api/items";
import { useItems, type ItemsParams } from "@/modules/inventory/hooks/useItems";
import {
  attentionCount,
  useAttentionCounts,
} from "@/modules/shared/hooks/useAttentionCounts";

/** Why a record is on the overview, most urgent first. */
export type AttentionKind = "expired" | "expiring" | "low";

const KIND_ORDER: readonly AttentionKind[] = ["expired", "expiring", "low"];

/** How far ahead "expiring" looks, in days. */
const EXPIRING_HORIZON_DAYS = 7;

/**
 * Each list is capped: the overview names the top few and counts the rest
 * into the bars, and a hundred of each is more than a household or a small
 * warehouse holds at once. A larger set undercounts the bars, never the rows.
 */
const ATTENTION_LIMIT = 100;

export interface AttentionRecord {
  item: Item;
  kind: AttentionKind;
}

/**
 * One row per record, at its most urgent reason. A yoghurt that is expiring
 * *and* belongs to a short product is one thing to look at, and the date is
 * what makes it urgent — counting it twice would inflate both the heading
 * and the bar.
 */
export function mergeAttention(
  lists: Record<AttentionKind, readonly Item[]>,
): AttentionRecord[] {
  const seen = new Set<string>();
  const merged: AttentionRecord[] = [];
  for (const kind of KIND_ORDER) {
    for (const item of lists[kind]) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      merged.push({ item, kind });
    }
  }
  return merged;
}

export interface AttentionGroup {
  key: string;
  kind: AttentionKind;
  /** The record behind the row. */
  items: Item[];
}

/**
 * What the attention card lists for dated records. A date belongs to a
 * record, so expired and expiring records are rows of their own. A
 * threshold belongs to a product, so short stock is not grouped here at
 * all: those rows come from the products list (`useDashboardAttention`'s
 * `lowProducts`), which also names the product that has nothing left.
 */
export function groupAttention(
  records: readonly AttentionRecord[],
): AttentionGroup[] {
  return records
    .filter(({ kind }) => kind !== "low")
    .map(({ item, kind }) => ({
      key: `${kind}:${item.id}`,
      kind,
      items: [item],
    }));
}

export interface StorageComposition {
  zoneId: string;
  /** Records anywhere under the zone — the same count its card shows. */
  count: number;
  segments: { bad: number; warn: number; low: number; ok: number };
}

function collectSubtreeIds(zone: StorageLocationNode, into: Set<string>) {
  into.add(zone.id);
  for (const child of zone.children) collectSubtreeIds(child, into);
}

/** Where a place stands: the name it goes by and the place above it. */
export interface PlaceLink {
  name: string;
  parent_id: string | null;
}

/**
 * What each zone is made of, in records. A record counts toward a zone when
 * its location is anywhere below it, which is how the zone's own
 * `subtree_items_count` counts; records outside every zone (a location a
 * module owns and the tree hides) count toward none. `ok` is what is left.
 *
 * The zones arrive with the levels the overview loaded, not the whole tree,
 * so a record standing deeper is placed by climbing from its location
 * through `parentOf` (the places above it, read by id) until the climb
 * reaches a zone.
 */
export function buildStorageComposition(
  zones: readonly StorageLocationNode[],
  records: readonly AttentionRecord[],
  parentOf: ReadonlyMap<string, string | null> = new Map(),
): StorageComposition[] {
  const zoneOf = new Map<string, string>();
  for (const zone of zones) {
    const ids = new Set<string>();
    collectSubtreeIds(zone, ids);
    for (const id of ids) zoneOf.set(id, zone.id);
  }
  const owner = (locationId: string): string | undefined => {
    const seen = new Set<string>();
    let current: string | null | undefined = locationId;
    while (current && !seen.has(current)) {
      const zoneId = zoneOf.get(current);
      if (zoneId) return zoneId;
      seen.add(current);
      current = parentOf.get(current);
    }
    return undefined;
  };
  const segmentsOf = new Map(
    zones.map((zone) => [zone.id, { bad: 0, warn: 0, low: 0, ok: 0 }]),
  );
  for (const { item, kind } of records) {
    const segments = segmentsOf.get(owner(item.location_id) ?? "");
    if (!segments) continue;
    if (kind === "expired") segments.bad += 1;
    else if (kind === "expiring") segments.warn += 1;
    else segments.low += 1;
  }
  return zones.map((zone) => {
    const segments = segmentsOf.get(zone.id) ?? {
      bad: 0,
      warn: 0,
      low: 0,
      ok: 0,
    };
    const count = zone.subtree_items_count;
    segments.ok = Math.max(
      0,
      count - segments.bad - segments.warn - segments.low,
    );
    return { zoneId: zone.id, count, segments };
  });
}

/** The most places one request names (the endpoint's own cap is 200). */
const PLACES_CHUNK = 100;
/** Climbing stops here: a tree this deep is a cycle in the data. */
const MAX_CLIMB = 12;

/**
 * The places the overview's records stand in, and the chain of places above
 * them, read by id: a few small requests, one per level climbed, instead of
 * the organization's whole tree. Archived and virtual places are included, a
 * record may stand in one.
 */
function useRecordPlaces(locationIds: readonly string[]) {
  const key = [...new Set(locationIds)].sort().join(",");
  return useQuery({
    queryKey: [...queryKeys.storages.all, "record-places", key],
    queryFn: async () => {
      const places = new Map<string, PlaceLink>();
      let frontier = key ? key.split(",") : [];
      for (let level = 0; level < MAX_CLIMB && frontier.length > 0; level++) {
        const pages = await Promise.all(
          Array.from(
            { length: Math.ceil(frontier.length / PLACES_CHUNK) },
            (_, i) =>
              storagesApi.getPage({
                ids: frontier.slice(i * PLACES_CHUNK, (i + 1) * PLACES_CHUNK),
                usage: "all",
                include_archived: true,
                counts: false,
                limit: PLACES_CHUNK,
              }),
          ),
        );
        const next = new Set<string>();
        for (const row of pages.flatMap((page) => page.items)) {
          places.set(row.id, {
            name: row.name,
            parent_id: row.parent_id ?? null,
          });
          if (row.parent_id && !places.has(row.parent_id)) {
            next.add(row.parent_id);
          }
        }
        frontier = [...next];
      }
      return places;
    },
    enabled: key !== "",
    staleTime: 60_000,
  });
}

interface DashboardAttentionOptions {
  excludeModuleContexts: boolean;
  zones: readonly StorageLocationNode[];
}

/**
 * What the inventory overview has to say: the records that need a hand,
 * grouped for the attention card, and each zone's composition for the
 * storage bars. The rows come from three list queries the products screen
 * already answers; the heading's number comes from the one count the
 * statistics health card reads too.
 */
export function useDashboardAttention({
  excludeModuleContexts,
  zones,
}: DashboardAttentionOptions) {
  const base: ItemsParams = {
    exclude_module_contexts: excludeModuleContexts,
    limit: ATTENTION_LIMIT,
    offset: 0,
  };
  const expired = useItems({ ...base, only_expired: true });
  const expiring = useItems({
    ...base,
    expiring_days: EXPIRING_HORIZON_DAYS,
    sort_by: "expiry_date",
    sort_order: "asc",
  });
  const low = useItems({ ...base, only_low_stock: true });

  const records = useMemo(
    () =>
      mergeAttention({
        expired: expired.data?.items ?? [],
        expiring: expiring.data?.items ?? [],
        low: low.data?.items ?? [],
      }),
    [expired.data, expiring.data, low.data],
  );
  const groups = useMemo(() => groupAttention(records), [records]);
  const places = useRecordPlaces(records.map(({ item }) => item.location_id));
  const locations = useMemo(
    () => places.data ?? new Map<string, PlaceLink>(),
    [places.data],
  );
  const composition = useMemo(
    () =>
      buildStorageComposition(
        zones,
        records,
        new Map([...locations].map(([id, place]) => [id, place.parent_id])),
      ),
    [zones, records, locations],
  );

  // The heading's number, from the one endpoint the statistics health card
  // reads too: expired + expiring soon + short products, uncapped and
  // product-level for low stock. The card's rows are the top of each list —
  // the cap undercounts rows, never the number. Counting the low share off
  // the capped `low` page is what let the two screens drift.
  const lowProducts = useQuery<LowStockProduct[]>({
    queryKey: [...queryKeys.stats.lowStock, excludeModuleContexts],
    queryFn: () =>
      itemsApi.getLowStockProducts({
        exclude_module_contexts: excludeModuleContexts,
      }),
  });
  const counts = useAttentionCounts(excludeModuleContexts);
  const count = attentionCount(counts.data);

  const queries = [expired, expiring, low, lowProducts, counts];
  // Each one read by name: a list that failed leaves its rows out of the card,
  // and the card has to say it is incomplete rather than look quiet.
  const failed =
    expired.isError ||
    expiring.isError ||
    low.isError ||
    lowProducts.isError ||
    counts.isError;
  return {
    groups,
    lowProducts: lowProducts.data ?? [],
    count,
    composition,
    locations,
    isLoading: queries.some((q) => q.isLoading),
    isError: failed,
    refetch: () => {
      for (const q of queries) if (q.isError) void q.refetch();
    },
  };
}
