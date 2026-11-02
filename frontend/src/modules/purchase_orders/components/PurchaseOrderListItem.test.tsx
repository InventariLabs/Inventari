import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { withLanguage } from "@/test/mocks/i18n";
import PurchaseOrderListItem from "./PurchaseOrderListItem";
import type { PurchaseOrder } from "@/modules/purchase_orders/types/purchase-orders";
import { purchaseOrderRow } from "@/test/factories/purchaseOrders";

const draftPO: PurchaseOrder = {
  id: "po-1",
  organization_id: "org-1",
  number: "PO/2026/001",
  status: "DRAFT",
  partner_id: "partner-1",
  scheduled_date: "2026-05-01",
  notes: null,
  currency: null,
  created_by: "user-1",
  confirmed_by: null,
  confirmed_at: null,
  cancelled_by: null,
  cancelled_at: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  lines: [
    {
      id: "line-1",
      purchase_order_id: "po-1",
      product_template_id: "pt-1",
      name: "Widget",
      quantity_ordered: "24",
      quantity_received: "0",
      unit_price: "18.50",
      uom_id: null,
      uom_symbol: null,
      tax_rate: null,
      line_number: 1,
      notes: null,
    },
  ],
};

const confirmedPO: PurchaseOrder = {
  ...draftPO,
  status: "CONFIRMED",
};

const pendingApprovalPO: PurchaseOrder = {
  ...draftPO,
  status: "PENDING_APPROVAL",
};

const callbacks = {
  canWrite: true,
  canManage: true,
  onView: vi.fn(),
  onEdit: vi.fn(),
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

describe("PurchaseOrderListItem", () => {
  it("says an order with an unpriced line has no price yet", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={{ ...purchaseOrderRow(draftPO), total_gross: null }}
        {...callbacks}
      />,
    );
    expect(screen.getByText("No price yet")).toBeInTheDocument();
  });

  it("renders PO number", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
  });

  it("renders DRAFT badge", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("renders CONFIRMED badge", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(confirmedPO)}
        {...callbacks}
      />,
    );
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });

  it("shows line count", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(screen.getByText(/1.*line/i)).toBeInTheDocument();
  });

  it("shows scheduled date when present, formatted", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(screen.queryByText("2026-05-01")).not.toBeInTheDocument();
    expect(screen.getByText(/May 1, 2026/)).toBeInTheDocument();
  });

  it("shows edit and confirm buttons for DRAFT", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /confirm/i }),
    ).toBeInTheDocument();
  });

  it("keeps cancel out of the row for DRAFT, in the menu", async () => {
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("shows cancel in the danger colour", async () => {
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    const cancel = screen.getByRole("button", { name: /cancel/i });
    expect(cancel.className).toContain("text-on-danger");
  });

  it("hides edit and confirm buttons for CONFIRMED", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(confirmedPO)}
        {...callbacks}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Confirm" }),
    ).not.toBeInTheDocument();
  });

  it("shows cancel in the menu for CONFIRMED", async () => {
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(confirmedPO)}
        {...callbacks}
      />,
    );
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("calls onView when PO name is clicked", async () => {
    const onView = vi.fn();
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        onView={onView}
      />,
    );
    await user.click(screen.getByText("PO/2026/001"));
    expect(onView).toHaveBeenCalledOnce();
  });

  it("calls onEdit when edit button is clicked", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        onEdit={onEdit}
      />,
    );
    await user.click(screen.getByRole("button", { name: /edit/i }));
    expect(onEdit).toHaveBeenCalledOnce();
  });

  it("calls onConfirm when confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("calls onCancel when cancel is chosen in the menu", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        onCancel={onCancel}
      />,
    );
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});

/**
 * on phones the action row collapses into a "⋯" menu — three labelled
 * buttons overflow a 390 px viewport and "Cancel" was unreachable. The mobile
 * matchMedia override is scoped to this describe block.
 */
describe("PurchaseOrderListItem — mobile (< sm)", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it("collapses actions into an overflow menu", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /^Edit$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Cancel order$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /more actions/i }),
    ).toBeInTheDocument();
  });

  it("fires callbacks from the overflow menu", async () => {
    const onEdit = vi.fn();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        onEdit={onEdit}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole("button", { name: /more actions/i }));
    await user.click(screen.getByRole("button", { name: /^Edit$/i }));
    expect(onEdit).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: /more actions/i }));
    await user.click(screen.getByRole("button", { name: /^Cancel order$/i }));
    expect(onCancel).toHaveBeenCalledOnce();

    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("PurchaseOrderListItem — receipt progress", () => {
  // The row asks the viewport where to put its actions; jsdom has no
  // matchMedia unless a test provides one.
  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  const callbacks = {
    canWrite: true,
    canManage: true,
    onView: vi.fn(),
    onEdit: vi.fn(),
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };

  it("shows how much of a confirmed order has arrived", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow({
          ...confirmedPO,
          lines: [{ ...confirmedPO.lines[0], quantity_received: "6" }],
        })}
        {...callbacks}
      />,
    );

    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "6");
    expect(meter).toHaveAttribute("aria-valuemax", "24");
    // The counter names itself — a bare "6/24" never said what it counted.
    expect(screen.getByText("Received 6 of 24")).toBeInTheDocument();
  });

  it("writes the received and ordered figures with the reader's decimal mark", async () => {
    // 1 of 2.5 kg read "1/2.5" beside "1/2,5" in the meter's own label — the
    // visible text was the one place the raw JavaScript numbers got through.
    await withLanguage("pl", () => {
      render(
        <PurchaseOrderListItem
          purchaseOrder={purchaseOrderRow({
            ...confirmedPO,
            lines: [
              {
                ...confirmedPO.lines[0],
                quantity_ordered: "2.500",
                quantity_received: "1.000",
              },
            ],
          })}
          {...callbacks}
        />,
      );

      expect(screen.getByText("Przyjęto 1 z 2,5")).toBeInTheDocument();
      expect(screen.queryByText(/2\.5/)).not.toBeInTheDocument();
    });
  });

  it("shows nothing while the order is still a draft", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
      />,
    );
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("does not add pieces, kilograms and packs into one number", () => {
    // 20 pcs + 12.5 kg + 30 pack read "56.5/62.5" — a sum in no unit at all.
    // The line detail was always right; the row's total was the invented one.
    const mixedLines = [
      {
        ...confirmedPO.lines[0],
        id: "l1",
        uom_symbol: "pcs",
        quantity_ordered: "20",
        quantity_received: "18",
      },
      {
        ...confirmedPO.lines[0],
        id: "l2",
        uom_symbol: "kg",
        quantity_ordered: "12.5",
        quantity_received: "12.5",
      },
      {
        ...confirmedPO.lines[0],
        id: "l3",
        uom_symbol: "pack",
        quantity_ordered: "30",
        quantity_received: "26",
      },
    ];
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow({ ...confirmedPO, lines: mixedLines })}
        {...callbacks}
      />,
    );

    expect(screen.queryByText("56.5/62.5")).not.toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(
      screen.getByText("Received: 18/20 pcs. · 12.5/12.5 kg · 26/30 pack"),
    ).toBeInTheDocument();
  });

  it("leaves an order waiting for approval a way out", async () => {
    // The row used to render no action at all for PENDING_APPROVAL, and the
    // detail page bar hid Cancel the same way — so an order whose request had
    // been withdrawn could not be moved anywhere from the interface.
    const user = userEvent.setup();
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(pendingApprovalPO)}
        {...callbacks}
      />,
    );

    await user.click(screen.getByRole("button", { name: /more actions/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(callbacks.onCancel).toHaveBeenCalled();
  });

  it("offers no cancel to an account that writes but does not manage", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        canManage={false}
      />,
    );

    // Edit and Confirm are writes; Cancel answers to purchase_orders:manage.
    expect(
      screen.getByRole("button", { name: /confirm/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /more actions/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
  });

  it("gives a read-only account no row actions at all", () => {
    render(
      <PurchaseOrderListItem
        purchaseOrder={purchaseOrderRow(draftPO)}
        {...callbacks}
        canWrite={false}
      />,
    );

    // The number stays — reading the row is what the account may do.
    expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /confirm/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
  });
});
