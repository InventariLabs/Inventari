import type { PutawayOccupancyOverview } from "@/modules/warehouse/api/putaway";
import { formatQuantityLocale } from "@/utils/formatters";

export type OccupancyNode = PutawayOccupancyOverview["nodes"][number];
export type OccupancyCell = NonNullable<OccupancyNode["cell"]>;
export type OccupancyEntry = OccupancyCell["entries"][number];

/** The filters of the screen; `all` filters nothing. */
export type OccupancyFilter = "all" | "full" | "over" | "empty" | "noLimit";

export const OCCUPANCY_FILTERS: OccupancyFilter[] = [
  "all",
  "full",
  "over",
  "empty",
  "noLimit",
];

/** A product standing on a shelf, with the quantity the search found. */
export interface OccupancyHit {
  productId: string;
  name: string;
  quantity: string;
  unit: string | null;
}

/** What a search found, per shelf; null while nothing is searched. */
export type HitsByLocation = Map<string, OccupancyHit[]> | null;

/** Whether a shelf belongs under a filter. "Full" includes over the limit. */
export function passesFilter(
  cell: OccupancyCell,
  filter: OccupancyFilter,
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "full":
      return cell.status === "nearly_full" || cell.status === "over";
    case "over":
      return cell.status === "over";
    case "empty":
      return cell.status === "empty";
    case "noLimit":
      return cell.status === "no_limit";
  }
}

/** What a "where is…" search found on one shelf. */
export function hitsAt(
  hits: HitsByLocation,
  locationId: string,
): OccupancyHit[] {
  return hits?.get(locationId) ?? [];
}

/**
 * The product a shelf of one product holds. The floor's overview counts a
 * shelf's products and names them only where it takes one to say what lies
 * there — the bar's limited products, and the one product of such a shelf.
 */
export function onlyProduct(cell: OccupancyCell): OccupancyEntry | null {
  if (cell.products !== 1) return null;
  return cell.entries.find((entry) => Number(entry.quantity) > 0) ?? null;
}

/** "50 pcs": what a search found on a shelf, as it is printed. */
export function hitQuantity(hit: {
  quantity: string;
  unit: string | null;
}): string {
  return `${formatQuantityLocale(hit.quantity)} ${hit.unit ?? ""}`.trim();
}

/**
 * The ids a filter and a search leave on screen: a shelf that passes both,
 * and every location above it. `null` when nothing filters, which every
 * caller reads as "show everything". `hits` is the search's answer, null
 * while there is none.
 *
 * The list is depth first with each parent before its children, so one pass
 * from the end sees every child before the parent that needs it.
 */
export function visibleNodeIds(
  nodes: OccupancyNode[],
  filter: OccupancyFilter,
  hits: HitsByLocation,
): Set<string> | null {
  if (filter === "all" && !hits) return null;
  const visible = new Set<string>();
  for (let i = nodes.length - 1; i >= 0; i--) {
    const node = nodes[i];
    const passes =
      node.cell !== null &&
      passesFilter(node.cell, filter) &&
      (!hits || hitsAt(hits, node.location_id).length > 0);
    if (passes || visible.has(node.location_id)) {
      visible.add(node.location_id);
      if (node.parent_id) visible.add(node.parent_id);
    }
  }
  return visible;
}

/**
 * The rows of the tree as the reader sees them: the nodes that pass the
 * filter, minus everything under a folded location.
 */
export function visibleNodes(
  nodes: OccupancyNode[],
  visible: Set<string> | null,
  folded: Set<string>,
): OccupancyNode[] {
  const rows: OccupancyNode[] = [];
  // Rows deeper than this are hidden under a folded location.
  let hideBelow: number | null = null;
  for (const node of nodes) {
    if (hideBelow !== null) {
      if (node.depth > hideBelow) continue;
      hideBelow = null;
    }
    if (visible && !visible.has(node.location_id)) continue;
    rows.push(node);
    if (node.has_children && folded.has(node.location_id)) {
      hideBelow = node.depth;
    }
  }
  return rows;
}

/** Tailwind classes for a status: the bar, and the number beside it. */
export function statusTone(status: OccupancyCell["status"]): {
  bar: string;
  text: string;
} {
  switch (status) {
    case "over":
      return { bar: "bg-red-500", text: "text-on-danger" };
    case "nearly_full":
      return { bar: "bg-amber-500", text: "text-on-warning" };
    case "ok":
      return { bar: "bg-blue-600", text: "text-on" };
    default:
      return { bar: "bg-gray-400", text: "text-on-secondary" };
  }
}

/** The path of a node from its warehouse: "Main › Cold Storage › Shelf 1". */
export function pathOf(
  byId: Map<string, OccupancyNode>,
  node: OccupancyNode,
): string {
  const names: string[] = [];
  let current: OccupancyNode | undefined = node;
  while (current) {
    names.unshift(current.name);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return names.join(" › ");
}
