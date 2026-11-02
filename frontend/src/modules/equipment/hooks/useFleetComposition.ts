import type { Category } from "@/types";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";
import {
  equipmentAssetsApi,
  type EquipmentAssetItem,
} from "@/modules/equipment/api/equipment_assets";
import { getEquipmentMeta } from "@/modules/equipment/components/assetUtils";

/**
 * The parts of one category's bar, each asset counted in exactly one: issued,
 * then in service, and of what stands on the shelf, the assets whose warranty
 * is about to end. Where an asset is comes first, so "11 checked out" under a
 * row is every checked-out asset in it; a held asset's ending warranty is on
 * the attention card, not in the bar.
 */
export interface FleetSegments {
  warn: number;
  issued: number;
  service: number;
  ok: number;
}

export interface FleetCategoryRow {
  /** The category id, or "none" for assets filed under no category. */
  key: string;
  category: Category | null;
  count: number;
  segments: FleetSegments;
}

const UNCATEGORISED = "none";

function segmentOf(
  asset: EquipmentAssetItem,
  warrantyEnding: ReadonlySet<string>,
): keyof FleetSegments | null {
  // The open assignment is the source of truth for "checked out"; the
  // status can lag behind it, and the dashboard's own tiles count a held
  // asset as issued whatever its status says.
  const held = asset.holder_name != null;
  const { status } = getEquipmentMeta(asset);
  if (held) return "issued";
  if (status === "RETIRED") return null;
  if (status === "MAINTENANCE") return "service";
  if (warrantyEnding.has(asset.id)) return "warn";
  return "ok";
}

/**
 * The fleet by category. Pure, so the rule for which part an asset counts in
 * is tested without a server.
 *
 * Retired assets are out of the fleet. Rows run largest first; equal counts
 * go by name, and the row of uncategorised assets comes last.
 */
export function bucketFleet(
  assets: readonly EquipmentAssetItem[],
  warrantyEnding: ReadonlySet<string>,
): FleetCategoryRow[] {
  const rows = new Map<string, FleetCategoryRow>();
  for (const asset of assets) {
    const segment = segmentOf(asset, warrantyEnding);
    if (!segment) continue;
    const key = asset.category?.id ?? asset.category_id ?? UNCATEGORISED;
    let row = rows.get(key);
    if (!row) {
      row = {
        key,
        category: asset.category ?? null,
        count: 0,
        segments: { warn: 0, issued: 0, service: 0, ok: 0 },
      };
      rows.set(key, row);
    }
    row.count += 1;
    row.segments[segment] += 1;
  }
  return [...rows.values()].sort(
    (a, b) =>
      Number(a.key === UNCATEGORISED) - Number(b.key === UNCATEGORISED) ||
      b.count - a.count ||
      (a.category?.name ?? "").localeCompare(b.category?.name ?? ""),
  );
}

/** The most the asset list hands out in one request. */
const FLEET_PAGE = 200;

/**
 * Every asset, page by page. The bars compare categories, so a fleet cut at
 * one page would draw the first two hundred assets as if they were all of it.
 */
export async function fetchWholeFleet(): Promise<EquipmentAssetItem[]> {
  const byId = new Map<string, EquipmentAssetItem>();
  let offset = 0;
  for (;;) {
    const page = await equipmentAssetsApi.listAssets({
      sort: "name",
      sort_dir: "asc",
      limit: FLEET_PAGE,
      offset,
    });
    for (const asset of page.items) byId.set(asset.id, asset);
    offset += page.items.length;
    if (page.items.length < FLEET_PAGE || offset >= page.total) {
      return [...byId.values()];
    }
  }
}

/** The whole fleet, under the asset-list key every asset write clears. */
export function useFleetAssets() {
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.assets.list({ whole: true }),
    queryFn: fetchWholeFleet,
  });
}
