import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@/test/utils";
import { PricelistComparisonCard } from "./PricelistComparisonCard";
import type { PartnerPricelist } from "../api/pricelist";

vi.mock("@/components/ui/ProductCombobox", () => ({
  ProductCombobox: () => <div data-testid="product-combobox-stub" />,
}));

const entry = (
  id: string,
  partner_id: string,
  unit_price: string,
  currency: string,
): PartnerPricelist =>
  ({
    id,
    partner_id,
    unit_price,
    currency,
    valid_from: "2026-01-01",
    valid_to: null,
  }) as unknown as PartnerPricelist;

describe("PricelistComparisonCard", () => {
  it("lists the offers in the order the server gave, never re-sorted by the bare number", () => {
    // The server puts the house currency first; 4.00 EUR is not "cheaper"
    // than 5.00 in the organization's own money.
    render(
      <PricelistComparisonCard
        compareProduct={{ name: "Gadget" } as never}
        entries={[
          entry("a", "p-local", "5.00", "USD"),
          entry("b", "p-abroad", "4.00", "EUR"),
        ]}
        supplierNames={
          new Map([
            ["p-local", "Local Supply Co"],
            ["p-abroad", "Abroad Ltd"],
          ])
        }
        searchProducts={vi.fn()}
        onSelect={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Local Supply Co")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Abroad Ltd")).toBeInTheDocument();
  });
});
