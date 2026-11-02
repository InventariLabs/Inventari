import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { PODetailsCard } from "./PODetailsCard";
import type { PurchaseOrder } from "../types/purchase-orders";

vi.mock("@/hooks/useDocumentCurrency", () => ({
  useDocumentCurrency: () => "USD",
}));

const order = (totalGross: string | null) =>
  ({
    id: "po-1",
    number: "PO/2026/017",
    status: "DRAFT",
    currency: "USD",
    scheduled_date: null,
    created_at: "2026-01-01T00:00:00",
    confirmed_at: null,
    notes: null,
    total_gross: totalGross,
    lines: [],
  }) as unknown as PurchaseOrder;

describe("PODetailsCard", () => {
  it("says an order with an unpriced line has no price yet, not 0.00", () => {
    render(<PODetailsCard po={order(null)} partnerName="Northgate" />);

    expect(screen.getByText("No price yet")).toBeInTheDocument();
    expect(screen.queryByText(/0\.00/)).not.toBeInTheDocument();
  });

  it("prints the total of an order it can state", () => {
    render(<PODetailsCard po={order("120.00")} partnerName="Northgate" />);

    expect(screen.getByText(/120\.00/)).toBeInTheDocument();
    expect(screen.queryByText("No price yet")).not.toBeInTheDocument();
  });
});
