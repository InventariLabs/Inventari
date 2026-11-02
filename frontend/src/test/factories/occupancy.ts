import type {
  PutawayOccupancy,
  PutawayOccupancyOverview,
} from "@/modules/warehouse/api/putaway";
import type { StockQuantsPage } from "@/lib/api/stockQuants";
import type {
  OccupancyCell,
  OccupancyEntry,
  OccupancyNode,
} from "@/modules/warehouse/components/occupancy/occupancyModel";

/** Test data for the occupancy screen: a small floor with every state on it. */
export function entry(
  name: string,
  quantity: string,
  limit: string | null,
  unit = "pcs",
): OccupancyEntry {
  const share =
    limit === null
      ? null
      : Math.round((Number(quantity) / Number(limit)) * 100);
  return {
    product_template_id: `p-${name}`,
    product_template_name: name,
    product_unit_symbol: unit,
    quantity,
    max_quantity: limit,
    share,
  };
}

export function cell(
  id: string,
  name: string,
  entries: OccupancyEntry[],
): OccupancyCell {
  const limited = entries.filter((e) => e.share !== null);
  const stocked = entries.filter((e) => Number(e.quantity) > 0);
  const fill = limited.length
    ? limited.reduce((sum, e) => sum + (e.share ?? 0), 0)
    : null;
  const status: OccupancyCell["status"] =
    stocked.length === 0
      ? "empty"
      : fill === null
        ? "no_limit"
        : fill > 100
          ? "over"
          : fill >= 85
            ? "nearly_full"
            : "ok";
  return {
    location_id: id,
    location_name: name,
    entries,
    capacity_product_name: null,
    capacity_used: null,
    capacity_max: null,
    capped_products: limited.length,
    products: stocked.length,
    fill,
    status,
    unmeasured: stocked.some((e) => e.share === null),
    items_count: stocked.length,
  };
}

const summary = (
  shelves: number,
  withLimit: number,
  full: number,
  over: number,
  empty: number,
  average: number | null,
) => ({
  shelves,
  with_limit: withLimit,
  full,
  over,
  empty,
  average_fill: average,
});

/**
 * The cell as the floor's overview sends it: the limited products — the
 * bar's segments — and the product of a shelf that holds one; the rest is
 * counted in `products`. The shelf's own read (`shelfRead`) lists them all.
 */
export function overviewCell(
  id: string,
  name: string,
  entries: OccupancyEntry[],
): OccupancyCell {
  const full = cell(id, name, entries);
  const alone = full.products === 1;
  return {
    ...full,
    entries: entries.filter(
      (e) => e.share !== null || (alone && Number(e.quantity) > 0),
    ),
  };
}

/** Every product of each shelf a test built, for the shelf's own read. */
const shelfContents = new Map<string, OccupancyEntry[]>();

/** What `GET /putaway/occupancy/{id}` answers for a shelf built here. */
export function shelfRead(id: string): PutawayOccupancy {
  return {
    locations: [cell(id, id, shelfContents.get(id) ?? [])],
    signals: [],
  };
}

/**
 * What `GET /stock-quants?search=` answers over the shelves built here: one
 * row per product standing on a shelf whose name holds the search.
 */
export function stockRowsMatching(search: string): StockQuantsPage {
  const needle = search.toLowerCase();
  const items = [...shelfContents.entries()].flatMap(([shelf, entries]) =>
    entries
      .filter(
        (e) =>
          Number(e.quantity) > 0 &&
          (e.product_template_name ?? "").toLowerCase().includes(needle),
      )
      .map((e) => ({
        id: `${shelf}:${e.product_template_id}`,
        product_template_id: e.product_template_id,
        location_id: shelf,
        quantity: e.quantity,
        reserved_quantity: "0",
        available_quantity: e.quantity,
        product_name: e.product_template_name,
        uom_symbol: e.product_unit_symbol,
      })),
  );
  return {
    items,
    total: items.length,
    limit: 500,
    offset: 0,
    has_more: false,
    total_capped: false,
  };
}

export function shelfNode(
  id: string,
  parent: string,
  depth: number,
  sequence: number,
  entries: OccupancyEntry[],
): OccupancyNode {
  shelfContents.set(id, entries);
  return {
    location_id: id,
    parent_id: parent,
    name: id,
    short_code: null,
    sequence,
    depth,
    has_children: false,
    cell: overviewCell(id, id, entries),
    summary: null,
  };
}

export function containerNode(
  id: string,
  parent: string | null,
  depth: number,
  s: ReturnType<typeof summary>,
): OccupancyNode {
  return {
    location_id: id,
    parent_id: parent,
    name: id,
    short_code: null,
    sequence: null,
    depth,
    has_children: true,
    cell: null,
    summary: s,
  };
}

export const floor: PutawayOccupancyOverview = {
  nodes: [
    containerNode("Main", null, 0, summary(5, 3, 2, 1, 1, 83)),
    containerNode("Cold", "Main", 1, summary(4, 3, 2, 1, 1, 83)),
    shelfNode("Fridge A", "Cold", 2, 10, [entry("Plums", "26", "50", "kg")]),
    shelfNode("Fridge B", "Cold", 2, 20, [
      entry("Gouda", "12", "40"),
      entry("Butter", "14", null),
    ]),
    shelfNode("Fridge C", "Cold", 2, 30, [entry("Gouda", "48", "40")]),
    shelfNode("Fridge D", "Cold", 2, 40, []),
    containerNode("Dry", "Main", 1, summary(1, 0, 0, 0, 0, null)),
    shelfNode("Rack 1", "Dry", 2, 10, [entry("Flour", "30", null, "kg")]),
  ],
  totals: summary(5, 3, 2, 1, 1, 83),
};
