import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { withLanguage } from "@/test/mocks/i18n";
import StockTakeItemFigures from "./StockTakeItemFigures";

function row(overrides: Partial<StockTakeItem>): StockTakeItem {
  return {
    id: "sti-1",
    stock_take_id: "st-1",
    item_id: "item-1",
    item_name: "Screws",
    item_brand: null,
    uom_symbol: "pcs",
    uom_rounding: "1",
    system_quantity: "0.000",
    counted_quantity: "5.000",
    difference: "5.000",
    shelf_location: null,
    notes: null,
    recount_requested: false,
    counts: [],
    discrepancy_reason_code: null,
    discrepancy_reason: null,
    is_discrepancy: 1,
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T10:30:00Z",
    ...overrides,
  };
}

describe("StockTakeItemFigures", () => {
  /** A unit found away from the location it is recorded on: on this
   * location nothing of it was expected, as the report states it. "Expected
   * 1, counted 1" beside a surplus badge contradicted itself. */
  it("expects nothing here of a unit found away from its location", () => {
    render(
      <StockTakeItemFigures
        stockTakeItem={row({
          system_quantity: "1.000",
          counted_quantity: "1.000",
          expected_location_id: "shelf-a",
        })}
        savedCount={1}
        discrepancy="surplus"
      />,
    );

    const text = document.body.textContent ?? "";
    expect(text).toMatch(/Expected:\s*0 /);
    expect(text).toContain("(+1 ");
  });

  /**
   * The card appended the catalogue's own symbol to a trimmed raw string, so
   * it read "0.000 pcs" where the product list for that same unit said
   * "2 szt." — and this is the screen where somebody types the number.
   */
  it("names the unit the way the reader's language names it", async () => {
    await withLanguage("pl", async () => {
      render(
        <StockTakeItemFigures
          stockTakeItem={row({})}
          savedCount={5}
          discrepancy="surplus"
        />,
      );

      const text = document.body.textContent ?? "";
      expect(text).toContain("0 szt.");
      expect(text).toContain("5 szt.");
      expect(text).not.toContain("pcs");
    });
  });

  /** The difference goes where the two counts went, unit included — the
   * report badge beside it has always carried one. */
  it("writes the difference in the row's own unit", async () => {
    await withLanguage("pl", async () => {
      render(
        <StockTakeItemFigures
          stockTakeItem={row({})}
          savedCount={5}
          discrepancy="surplus"
        />,
      );

      expect(screen.getByText(/\+5 szt\./)).toBeInTheDocument();
    });
  });

  /**
   * The step says how finely a count is typed, not what the record holds:
   * rounding 2.345 kg to the hundredths' "2,35 kg" told the counter a figure
   * the Stock screen beside it did not show.
   */
  it("shows the figure the record holds, not the unit's step", async () => {
    await withLanguage("pl", async () => {
      render(
        <StockTakeItemFigures
          stockTakeItem={row({
            uom_symbol: "kg",
            uom_rounding: "0.01",
            system_quantity: "2.345",
          })}
          savedCount={2}
          discrepancy="missing"
        />,
      );

      expect(screen.getByText(/2,345 kg/)).toBeInTheDocument();
      expect(screen.queryByText(/2,35 kg/)).not.toBeInTheDocument();
    });
  });
});
