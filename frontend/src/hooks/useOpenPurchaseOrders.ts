import { useMemo } from "react";
import { api, getEveryPage } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import type { components } from "@/types/api-generated";

type PurchaseOrder = components["schemas"]["PurchaseOrderSchema"];
type PurchaseOrderListResponse =
  components["schemas"]["PurchaseOrderListResponse"];

/** One outstanding line of a supplier's confirmed order. */
export interface OpenPurchaseOrderLine {
  poId: string;
  poNumber: string;
  poCurrency: string | null;
  poLineId: string;
  productTemplateId: string | null;
  name: string;
  /** What the supplier still owes, in the line's own unit. */
  outstanding: string;
  /** What was ordered, for the "ordered / received" pair on the screen. */
  ordered: string;
  uomId: string | null;
  uomSymbol: string | null;
  unitPrice: string | null;
  taxRate: string | null;
}

/** One confirmed order that still owes goods, with what it still owes. */
export interface OpenPurchaseOrder {
  id: string;
  number: string;
  currency: string | null;
  createdAt: string;
  lines: OpenPurchaseOrderLine[];
}

/**
 * The supplier's deliveries that are still expected.
 *
 * The receive screen loads an order's open lines as soon as the reader
 * names the supplier, so the shelf and the counts are filled in without
 * anybody retyping what the order already says. That read belongs to the
 * purchase-orders module, which the warehouse module must not import
 * (module boundaries): this hook reads its public HTTP contract instead,
 * and is skipped entirely when the module is off.
 *
 * A completed receipt has already moved `quantity_received`; an open one
 * has not, and the posting's over-receipt guard is what refuses a second
 * delivery of the same goods. The screen therefore shows what the order
 * still owes, which is the question the reader is answering at the door.
 */
export function useOpenPurchaseOrders(partnerId: string | null) {
  // The lines are what this screen receives, so it asks the list for them.
  const params = {
    partner_id: partnerId,
    status: "CONFIRMED",
    limit: 50,
    with_lines: true,
  };
  const query = useModuleQuery<PurchaseOrderListResponse>("purchase_orders", {
    queryKey: queryKeys.purchaseOrders.list(params),
    queryFn: async () => {
      const response = await api.get<PurchaseOrderListResponse>(
        "/purchase-orders",
        { params },
      );
      return response.data;
    },
    extraEnabled: Boolean(partnerId),
    // Naming the supplier asks again: what a delivery already took off the
    // order moved it since the cache last read it.
    staleTime: 0,
  });

  const { data } = query;
  const orders = useMemo(() => openPurchaseOrders(data?.items ?? []), [data]);

  return { ...query, orders };
}

/** A quantity with the arithmetic noise of two decimal strings removed. */
function quantity(value: number): string {
  return String(Math.round(value * 1e6) / 1e6);
}

function outstandingLines(order: PurchaseOrder): OpenPurchaseOrderLine[] {
  const lines: OpenPurchaseOrderLine[] = [];
  for (const line of order.lines) {
    const outstanding =
      Number(line.quantity_ordered) - Number(line.quantity_received);
    if (!(outstanding > 0)) continue;
    lines.push({
      poId: order.id,
      poNumber: order.number,
      poCurrency: order.currency ?? null,
      poLineId: line.id,
      productTemplateId: line.product_template_id,
      name: line.name,
      outstanding: quantity(outstanding),
      ordered: quantity(Number(line.quantity_ordered)),
      uomId: line.uom_id,
      uomSymbol: line.uom_symbol ?? null,
      unitPrice: line.unit_price,
      taxRate: line.tax_rate,
    });
  }
  return lines;
}

/** The orders that still owe goods, oldest delivery first. */
export function openPurchaseOrders(
  items: PurchaseOrder[],
): OpenPurchaseOrder[] {
  const open: OpenPurchaseOrder[] = [];
  for (const order of items) {
    const lines = outstandingLines(order);
    if (lines.length === 0) continue;
    open.push({
      id: order.id,
      number: order.number,
      currency: order.currency ?? null,
      createdAt: order.created_at,
      lines,
    });
  }
  // The oldest delivery first: that is the one standing at the door.
  open.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  return open;
}

/**
 * The supplier of one order, for a link that opens the receive screen on it.
 *
 * The order's own screen and its To do row name the order, not the supplier;
 * the receive screen loads expected lines by supplier, so it asks the order
 * whose they are. Same key as the order's own screen: one answer for both.
 */
export function useOrderSupplier(orderId: string | null) {
  const query = useModuleQuery<PurchaseOrder>("purchase_orders", {
    queryKey: queryKeys.purchaseOrders.detail(orderId ?? ""),
    queryFn: async () => {
      const response = await api.get<PurchaseOrder>(
        `/purchase-orders/${orderId}`,
      );
      return response.data;
    },
    extraEnabled: Boolean(orderId),
  });
  return { ...query, partnerId: query.data?.partner_id ?? null };
}

type LinkedReceipt = components["schemas"]["LinkedReceiptSchema"];

/** States in which a receipt still expects goods it has not brought. */
const OPEN_RECEIPT_STATUSES = new Set([
  "DRAFT",
  "CONFIRMED",
  "PENDING_APPROVAL",
]);

/**
 * The order's receipts that are open: drafted, confirmed or waiting for an
 * approval, and not yet posted.
 *
 * Such a receipt already speaks for part of what the order owes. A
 * delivery received beside it, on the receive screen, is weighed against
 * the order with that part spoken for — so the screen names the receipt
 * instead of leaving the reader to meet the refusal. Read through the
 * purchase-orders module's public HTTP contract, like the order itself.
 */
export function useOrderOpenReceipts(orderId: string | null) {
  const { data, error, isError, refetch } = useModuleQuery<LinkedReceipt[]>(
    "purchase_orders",
    {
      queryKey: queryKeys.purchaseOrders.linkedReceipts(orderId ?? ""),
      queryFn: () =>
        getEveryPage<LinkedReceipt>(
          `/purchase-orders/${orderId}/linked-receipts`,
        ),
      extraEnabled: Boolean(orderId),
    },
  );
  const receipts = useMemo(
    () =>
      (data ?? []).filter((receipt) =>
        OPEN_RECEIPT_STATUSES.has(receipt.status),
      ),
    [data],
  );
  // A failed read is not "no open receipts": the caller says it could not
  // look, rather than staying silent as if there were none.
  return { receipts, error, isError, refetch };
}
