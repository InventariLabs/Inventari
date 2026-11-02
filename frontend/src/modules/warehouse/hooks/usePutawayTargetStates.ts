import { useQueries, useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import {
  putawayCapacityApi,
  putawayOccupancyApi,
  type PutawayCapacityEntry,
  type PutawayLocationSetting,
  type PutawayOccupancy,
} from "@/modules/warehouse/api/putaway";

/**
 * What one target of a putaway rule holds, as the shared fill response
 * states it: the rule's product's pair where the product is limited, the
 * shelf's whole fill, and the mixing and limit count a rule that matches no
 * product reads instead.
 *
 * Nothing is computed here. The limit, the quantity standing against it and
 * the state (`nearly_full`, `over`, …) all arrive from the same reads the
 * Locations tab shows, so this screen can never call a target roomy that
 * the planner sends a delivery past.
 */
export interface PutawayTargetState {
  /** The rule's product's limit here and the unit it is counted in. */
  limit: { max: string; unit: string | null } | null;
  /** What of the product stands here (the wire's text). */
  used: string | null;
  /** The whole target's fill, from the shared fill response. */
  status: PutawayOccupancy["locations"][number]["status"] | null;
  /** The fill in percent — the sum of every limited product's share. */
  fill: number | null;
  /** How many products hold a share of this target. */
  cappedProducts: number;
  /** A product stands here with no limit of its own and is not counted. */
  unmeasured: boolean;
  /** The target takes one product only. */
  singleProduct: boolean;
  /** How many product limits the target carries. */
  limitCount: number;
}

/**
 * A target whose reads have not all arrived is absent from the map rather
 * than present with empty values: an unread limit is not "no limit", an
 * unread fill is not an empty shelf, so a summary or an overflow note drawn
 * from it would be a claim nobody checked.
 */

function stateOf(
  locationId: string,
  productTemplateId: string | null,
  capacity: PutawayCapacityEntry[],
  settings: PutawayLocationSetting[],
  occupancy: PutawayOccupancy,
): PutawayTargetState {
  const here = capacity.filter((entry) => entry.location_id === locationId);
  const entry =
    productTemplateId === null
      ? undefined
      : here.find((row) => row.product_template_id === productTemplateId);
  const cell = occupancy.locations.find(
    (row) => row.location_id === locationId,
  );
  const pair = cell?.entries.find(
    (row) => row.product_template_id === productTemplateId,
  );
  return {
    limit: entry
      ? {
          max: String(entry.max_quantity),
          unit: entry.product_unit_symbol ?? null,
        }
      : null,
    used: pair ? String(pair.quantity) : null,
    status: cell?.status ?? null,
    fill: cell?.fill ?? null,
    cappedProducts: cell?.capped_products ?? 0,
    unmeasured: cell?.unmeasured ?? false,
    singleProduct:
      settings.find((setting) => setting.location_id === locationId)
        ?.single_product ?? false,
    limitCount: here.length,
  };
}

/**
 * The state of every target on a rule's list whose reads have all arrived,
 * keyed by location.
 *
 * Three reads serve it: the organization's limits (also the unit symbols and
 * the limit counts), the chosen mixes, and the shared fill read per target.
 * All three refresh when the settings panel saves, which is how a limit
 * raised there shows in the rule editor without a reload.
 */
export function usePutawayTargetStates(
  locationIds: string[],
  productTemplateId: string | null,
): {
  stateByLocation: Map<string, PutawayTargetState>;
  isError: boolean;
  error: unknown;
  refetch: () => void;
} {
  const {
    data: capacity,
    isError: capacityFailed,
    error: capacityError,
    refetch: refetchCapacity,
  } = useQuery({
    queryKey: queryKeys.documents.putawayCapacityAll,
    queryFn: () => putawayCapacityApi.list(),
    enabled: locationIds.length > 0,
  });
  const {
    data: settings,
    isError: settingsFailed,
    error: settingsError,
    refetch: refetchSettings,
  } = useQuery({
    queryKey: queryKeys.documents.putawayCapacitySettings,
    queryFn: () => putawayCapacityApi.listSettings(),
    enabled: locationIds.length > 0,
  });
  const occupancyQueries = useQueries({
    queries: locationIds.map((locationId) => ({
      queryKey: queryKeys.documents.putawayOccupancy(locationId),
      queryFn: () => putawayOccupancyApi.get(locationId),
    })),
  });

  const stateByLocation = new Map<string, PutawayTargetState>();
  if (capacity && settings) {
    locationIds.forEach((locationId, index) => {
      const occupancy = occupancyQueries[index]?.data;
      if (!occupancy) return;
      stateByLocation.set(
        locationId,
        stateOf(locationId, productTemplateId, capacity, settings, occupancy),
      );
    });
  }

  const occupancyFailure = occupancyQueries.find((query) => query.isError);
  return {
    stateByLocation,
    isError: capacityFailed || settingsFailed || occupancyFailure !== undefined,
    error: capacityError ?? settingsError ?? occupancyFailure?.error,
    refetch: () => {
      void refetchCapacity();
      void refetchSettings();
      for (const query of occupancyQueries) void query.refetch();
    },
  };
}
