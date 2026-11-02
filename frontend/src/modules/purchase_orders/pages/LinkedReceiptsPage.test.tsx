import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import LinkedReceiptsPage from "./LinkedReceiptsPage";
import * as poHooks from "../hooks/usePurchaseOrders";
import { withLanguage } from "@/test/mocks/i18n";
import type { PurchaseOrder } from "@/modules/purchase_orders/types/purchase-orders";

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

vi.mock("../hooks/usePurchaseOrders", () => ({
  usePurchaseOrder: vi.fn(),
  useLinkedReceipts: vi.fn(),
  usePendingQuantities: vi.fn(),
}));

function purchaseOrder(over: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: "po-1",
    organization_id: "org-1",
    number: "PO/2026/002",
    status: "CONFIRMED",
    partner_id: null,
    scheduled_date: null,
    notes: null,
    currency: "PLN",
    created_by: "user-1",
    confirmed_by: null,
    confirmed_at: null,
    cancelled_by: null,
    cancelled_at: null,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    lines: [
      {
        id: "line-1",
        purchase_order_id: "po-1",
        product_template_id: null,
        name: "Dell Latitude 5540",
        quantity_ordered: "2.000",
        quantity_received: "0.000",
        unit_price: "4200.00",
        uom_id: null,
        uom_symbol: null,
        tax_rate: "23.00",
        line_number: 1,
        notes: null,
      },
    ],
    ...over,
  };
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/purchase-orders/po-1/linked-receipts"]}>
      <Routes>
        <Route
          path="/purchase-orders/:id/linked-receipts"
          element={<LinkedReceiptsPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

/**
 * The line's progress was the wire string verbatim — "0.000 / 2.000" with
 * the database's padding and mark, on the line directly above the percent
 * that already spoke the reader's language.
 */
describe("LinkedReceiptsPage — quantities speak the reader's mark", () => {
  beforeEach(() => {
    vi.mocked(poHooks.usePurchaseOrder).mockReturnValue({
      data: purchaseOrder(),
      isLoading: false,
    } as unknown as ReturnType<typeof poHooks.usePurchaseOrder>);
    vi.mocked(poHooks.useLinkedReceipts).mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof poHooks.useLinkedReceipts>);
    vi.mocked(poHooks.usePendingQuantities).mockReturnValue({});
  });

  it("prints the received/ordered pair as the language writes it", async () => {
    await withLanguage("pl", () => {
      renderPage();

      // "0.000" carries a piece unit's three decimals nobody typed and a
      // mark no Polish reader uses; the shared quantity formatter writes it
      // as 0 of 2 units.
      expect(
        screen.getByText("Przyjęto (zakończone): 0 / 2 jednostki"),
      ).toBeInTheDocument();
      expect(screen.queryByText(/0\.000 \/ 2\.000/)).not.toBeInTheDocument();
    });
  });

  it("keeps a fractional quantity fractional, with a comma", async () => {
    vi.mocked(poHooks.usePurchaseOrder).mockReturnValue({
      data: purchaseOrder({
        lines: [
          {
            ...purchaseOrder().lines[0],
            quantity_ordered: "2.500",
            quantity_received: "1.500",
            uom_symbol: "kg",
          },
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof poHooks.usePurchaseOrder>);

    await withLanguage("pl", () => {
      renderPage();

      expect(
        screen.getByText("Przyjęto (zakończone): 1,5 / 2,5 kg"),
      ).toBeInTheDocument();
    });
  });

  /**
   * "W drodze: 1" counted what is still on the way with a bare number beside
   * a line that said "1 / 3 kg" — the unit the figure is in was one line up
   * and missing from the count itself.
   */
  it("gives the in-transit count the line's own unit", async () => {
    vi.mocked(poHooks.usePendingQuantities).mockReturnValue({
      "line-1": "1.000",
    });
    vi.mocked(poHooks.usePurchaseOrder).mockReturnValue({
      data: purchaseOrder({
        lines: [
          {
            ...purchaseOrder().lines[0],
            quantity_ordered: "3.000",
            quantity_received: "2.000",
            uom_symbol: "kg",
          },
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof poHooks.usePurchaseOrder>);

    await withLanguage("pl", () => {
      renderPage();

      expect(screen.getByText(/W drodze: 1 kg/)).toBeInTheDocument();
    });
  });
});
