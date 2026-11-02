import type {
  PurchaseOrder,
  PurchaseOrderRow,
} from "@/modules/purchase_orders/types/purchase-orders";

/**
 * The purchase-order list row the server builds from an order
 * (`PurchaseOrderListRowSchema.of`): the lines counted and summed per unit,
 * in the order they first name it, and left out.
 */
export function purchaseOrderRow(order: PurchaseOrder): PurchaseOrderRow {
  const progress = new Map<
    string | null,
    { unit: string | null; ordered: number; received: number }
  >();
  for (const line of order.lines) {
    const key = unitKey(line);
    const group = progress.get(key) ?? { unit: key, ordered: 0, received: 0 };
    group.ordered += Number(line.quantity_ordered ?? 0);
    group.received += Number(line.quantity_received ?? 0);
    progress.set(key, group);
  }
  const { lines, ...rest } = order;
  return {
    ...rest,
    line_count: lines.length,
    unit_progress: [...progress.values()].map((group) => ({
      unit: group.unit,
      ordered: String(group.ordered),
      received: String(group.received),
    })),
  };
}

/** The unit a line is grouped under; a blank symbol is no unit. */
function unitKey(line: PurchaseOrder["lines"][number]): string | null {
  return line.uom_symbol?.trim() || null;
}
