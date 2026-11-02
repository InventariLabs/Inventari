import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import {
  putawayCapacityApi,
  type PutawayOccupancyOverview,
} from "@/modules/warehouse/api/putaway";
import { FillBar } from "@/modules/warehouse/components/occupancy/FillBar";
import type { OccupancyNode } from "@/modules/warehouse/components/occupancy/occupancyModel";
import { AverageFill } from "@/modules/warehouse/components/occupancy/AverageFill";

/**
 * How full a location is, as the compact bar on its row in the location tree.
 *
 * Every row of the tree renders this, and all of them read the same cached
 * answer — the occupancy screen's — so a tree of a thousand rows asks the
 * server once. A location nobody limited draws nothing here: the tree already
 * shows its record count, and a dashed "no limit" on every unlimited row would
 * be noise on a screen whose job is the shape of the warehouse.
 */
/** The overview indexed by location, once per answer rather than once per row. */
const indexes = new WeakMap<object, Map<string, OccupancyNode>>();

function indexOf(overview: PutawayOccupancyOverview) {
  let index = indexes.get(overview);
  if (!index) {
    index = new Map(overview.nodes.map((n) => [n.location_id, n]));
    indexes.set(overview, index);
  }
  return index;
}

export default function StorageTreeOccupancySlot({
  data,
}: {
  data: { storageId: string };
}) {
  const { data: overview } = useQuery({
    queryKey: queryKeys.documents.putawayOccupancyOverview,
    queryFn: () => putawayCapacityApi.occupancyOverview(),
    staleTime: 60_000,
    retry: false,
  });
  const node = overview && indexOf(overview).get(data.storageId);
  if (!node) return null;
  if (node.cell && node.cell.fill !== null) {
    return <FillBar cell={node.cell} size="compact" />;
  }
  if (node.summary?.average_fill != null) {
    return <AverageFill average={node.summary.average_fill} size="compact" />;
  }
  return null;
}
