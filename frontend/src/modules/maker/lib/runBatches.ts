import type { ProductionOrder, RunBatch } from "@/modules/maker/types/maker";

/**
 * Every batch a run's output was filed under, the run's own first.
 *
 * A run filled in portions has one per name its portions went under; the page
 * of one run carries them all. A run read from a list, or one that put
 * everything in a single batch, has the one its own fields name.
 */
export function runBatches(order: ProductionOrder): RunBatch[] {
  if (order.output_batches && order.output_batches.length > 0)
    return order.output_batches;
  if (!order.output_lot_id) return [];
  return [
    {
      lot_id: order.output_lot_id,
      lot_name: order.output_lot_name ?? "",
      status: order.output_lot_status ?? "active",
      best_before: order.best_before ?? null,
    },
  ];
}

/** The codes of the batches, for a line that has room for them all. A run
 *  that has filed nothing yet speaks of the batch it plans to. */
export function runBatchNames(order: ProductionOrder): string {
  const batches = runBatches(order);
  if (batches.length === 0) return order.output_lot_name ?? "";
  return batches.map((batch) => batch.lot_name).join(", ");
}
