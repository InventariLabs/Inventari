import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { PurchaseOrderTable } from "./PurchaseOrderTable";
import { isOverdue } from "./PurchaseOrderListItem";
import type { PurchaseOrder } from "@/modules/purchase_orders/types/purchase-orders";
import { purchaseOrderRow } from "@/test/factories/purchaseOrders";

const basePO: PurchaseOrder = {
  id: "po-1",
  organization_id: "org-1",
  number: "PO/2026/001",
  status: "CONFIRMED",
  partner_id: "partner-1",
  partner_name: "Acme Foods",
  scheduled_date: "2020-01-15",
  notes: null,
  currency: "EUR",
  total_gross: "120.00",
  created_by: "user-1",
  confirmed_by: null,
  confirmed_at: null,
  cancelled_by: null,
  cancelled_at: null,
  created_at: "2020-01-01T00:00:00",
  updated_at: "2020-01-01T00:00:00",
  lines: [
    {
      id: "line-1",
      purchase_order_id: "po-1",
      product_template_id: "pt-1",
      name: "Widget",
      quantity_ordered: "8",
      quantity_received: "3",
      unit_price: "15.00",
      uom_id: null,
      uom_symbol: null,
      tax_rate: null,
      line_number: 1,
      notes: null,
    },
  ],
} as PurchaseOrder;

// The row the list carries for that order.
const baseRow = purchaseOrderRow(basePO);

const handlers = {
  canWrite: true,
  canManage: true,
  onView: vi.fn(),
  onEdit: vi.fn(),
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

describe("PurchaseOrderTable", () => {
  it("says an order with an unpriced line has no price yet", () => {
    render(
      <PurchaseOrderTable
        purchaseOrders={[{ ...baseRow, total_gross: null }]}
        {...handlers}
      />,
    );

    expect(screen.getByText("No price yet")).toBeInTheDocument();
  });

  it("is a table whose columns name what each cell holds", () => {
    render(<PurchaseOrderTable purchaseOrders={[baseRow]} {...handlers} />);

    const headers = screen
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual([
      "Number",
      "Status",
      "Supplier",
      "Lines",
      "Scheduled",
      "Received",
      "Total",
      "Actions",
    ]);
    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Acme Foods")).toBeInTheDocument();
    // The "Received" header is the counter's legend; the cell holds the figure.
    expect(within(row).getByText("3/8 units")).toBeInTheDocument();
  });

  it("flags a confirmed order whose date has passed", () => {
    render(<PurchaseOrderTable purchaseOrders={[baseRow]} {...handlers} />);
    expect(screen.getByText("Overdue")).toBeInTheDocument();
  });

  it("does not flag a draft with a past date or a confirmed one in the future", () => {
    render(
      <PurchaseOrderTable
        purchaseOrders={[
          { ...baseRow, id: "a", status: "DRAFT" },
          { ...baseRow, id: "b", scheduled_date: "2999-01-01" },
        ]}
        {...handlers}
      />,
    );
    expect(screen.queryByText("Overdue")).not.toBeInTheDocument();
  });

  it("opens the order from its number", async () => {
    const onView = vi.fn();
    render(
      <PurchaseOrderTable
        purchaseOrders={[baseRow]}
        {...handlers}
        onView={onView}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "PO/2026/001" }));
    expect(onView).toHaveBeenCalledWith(baseRow);
  });

  it("drops the actions column for a read-only account", () => {
    render(
      <PurchaseOrderTable
        purchaseOrders={[baseRow]}
        {...handlers}
        canWrite={false}
      />,
    );
    expect(screen.queryByText("Actions")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
  });
});

describe("isOverdue", () => {
  it("compares the date, not the time of day", () => {
    const today = new Date(2026, 8, 26, 23, 59);
    expect(isOverdue({ ...baseRow, scheduled_date: "2026-09-26" }, today)).toBe(
      false,
    );
    expect(isOverdue({ ...baseRow, scheduled_date: "2026-09-25" }, today)).toBe(
      true,
    );
  });
});
