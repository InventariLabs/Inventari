import type { WarehouseReceiving } from "@/modules/warehouse/api/putaway";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/**
 * The receiving area the goods of a receipt stand in, when their warehouse
 * receives in two steps: they are not on a shelf yet, and a putaway task
 * waits to take them there.
 */
export function waitingInReceiving(
  document: WarehouseDocument,
  modes: WarehouseReceiving[] | undefined,
): string | null {
  const area = (modes ?? []).find(
    (mode) =>
      mode.two_step &&
      mode.receiving_location_id &&
      document.lines?.some(
        (line) => line.executed_location_id === mode.receiving_location_id,
      ),
  );
  return area?.receiving_location_name ?? null;
}
