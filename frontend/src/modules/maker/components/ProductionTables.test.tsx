import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProductionIngredientsTable } from "./ProductionIngredientsTable";
import { ProductionStockMovesTable } from "./ProductionStockMovesTable";
import { withLanguage } from "@/test/mocks/i18n";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import type {
  CostBreakdownEntry,
  ShortageEntry,
  ProductionOrderLine,
  StockMove,
} from "@/modules/maker/types/maker";

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

const line: ProductionOrderLine = {
  id: "line-1",
  production_order_id: "ord-1",
  child_template_id: "fb59c5f2-1111-2222-3333-444455556666",
  child_template_name: "Strawberries",
  consumed_qty: "2.0000",
  unit: "kg",
  source_location_id: "aa11bb22-cccc-dddd-eeee-ff0011223344",
  source_location_name: "Cold Storage",
  unit_cost_snapshot: "4.00",
  cost_source: "avco",
};

const move: StockMove = {
  id: "move-1",
  product_template_id: "fb59c5f2-1111-2222-3333-444455556666",
  product_template_name: "Strawberries",
  uom_symbol: "kg",
  from_location_id: "aa11bb22-cccc-dddd-eeee-ff0011223344",
  from_location_name: "Cold Storage",
  to_location_id: null,
  to_location_name: null,
  quantity: "2.0000",
  lot_id: "99887766-5544-3322-1100-aabbccddeeff",
  lot_code: "LOT-2026-08",
  created_at: null,
};

describe("ProductionIngredientsTable", () => {
  it("names the source location and keeps the id in the tooltip", () => {
    render(<ProductionIngredientsTable lines={[line]} />);

    const source = screen.getByTitle(line.source_location_id!);
    expect(source).toHaveTextContent("Cold Storage");
    expect(screen.queryByText(/aa11bb22/)).not.toBeInTheDocument();
  });

  it("falls back to a label when the location is gone", () => {
    render(
      <ProductionIngredientsTable
        lines={[{ ...line, source_location_name: null }]}
      />,
    );

    expect(screen.getByText(/Unknown location/)).toBeInTheDocument();
  });

  it("writes pcs the way the preview writes it, in the reader's language", async () => {
    // The order page was the third place with its own convention: the raw
    // symbol ("20000 pcs") under a preview saying "20 000 szt.". The same
    // session, the same ingredient, two words for one unit.
    const pcsLine = { ...line, consumed_qty: "20000.000", unit: "pcs" };
    await withLanguage("pl", () => {
      render(<ProductionIngredientsTable lines={[pcsLine]} />);

      expect(screen.getByText("20 000 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/pcs/)).not.toBeInTheDocument();
      expect(screen.queryByText(/20000/)).not.toBeInTheDocument();
    });
  });

  it("labels the shortage with the translated unit and grouped thousands", async () => {
    const plannedEntry: CostBreakdownEntry = {
      child_template_id: line.child_template_id,
      child_template_name: line.child_template_name,
      consumed_qty: "20000.000",
      unit: "pcs",
      unit_cost: "1.00",
      cost: "20000.00",
      percentage_of_total: "100",
      cost_source: "avco",
    };
    const short: ShortageEntry = {
      child_template_id: line.child_template_id,
      child_template_name: line.child_template_name ?? null,
      needed: "20000.000",
      available: "18.000",
      shortage: "19982.000",
      uom_symbol: "pcs",
      convertible: true,
      available_uom_symbol: "pcs",
    };
    await withLanguage("pl", () => {
      render(
        <ProductionIngredientsTable
          lines={[]}
          isPlanned
          planned={[plannedEntry]}
          shortages={new Map([[line.child_template_id, short]])}
        />,
      );

      expect(screen.getByText("20 000 szt.")).toBeInTheDocument();
      expect(screen.getByText(/brakuje 19 982 szt\./)).toBeInTheDocument();
      expect(screen.queryByText(/19982/)).not.toBeInTheDocument();
    });
  });

  it("names the shelves a planned run would draw from, before it runs", () => {
    // Closing a run cannot be undone, and the draw is deterministic — so
    // which shelf it will empty is an answer the draft's table owes the
    // reader while closing is still a choice.
    const plannedEntry: CostBreakdownEntry = {
      child_template_id: line.child_template_id,
      child_template_name: line.child_template_name,
      consumed_qty: "10.000",
      unit: "kg",
      unit_cost: null,
      cost: null,
      percentage_of_total: null,
      cost_source: "none",
      planned_draws: [
        {
          location_id: "aa11bb22-cccc-dddd-eeee-ff0011223344",
          location_name: "Cold Storage",
          quantity: "8.000",
        },
        {
          location_id: "bb22cc33-dddd-eeee-ffff-001122334455",
          location_name: "Pantry",
          quantity: "2.000",
        },
      ],
    };

    render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[plannedEntry]}
      />,
    );

    expect(screen.getByText(/← Cold Storage · 8 kg/)).toBeInTheDocument();
    expect(screen.getByText(/← Pantry · 2 kg/)).toBeInTheDocument();
    // The ids stay in the tooltips, out of the reading surface.
    expect(screen.queryByText(/aa11bb22/)).not.toBeInTheDocument();
    expect(screen.queryByText(/bb22cc33/)).not.toBeInTheDocument();
  });
});

describe("ProductionStockMovesTable", () => {
  it("shows product and lot names instead of truncated identifiers", () => {
    render(<ProductionStockMovesTable stockMoves={[move]} />, {
      wrapper: QueryWrapper,
    });

    expect(screen.getByTitle(move.product_template_id)).toHaveTextContent(
      "Strawberries",
    );
    expect(screen.getByTitle(move.lot_id!)).toHaveTextContent("LOT-2026-08");
    expect(screen.queryByText(/fb59c5f2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/99887766/)).not.toBeInTheDocument();
  });

  it("gives the moved amount the same unit convention as the tables above", async () => {
    const pcsMove: StockMove = {
      ...move,
      quantity: "12.000",
      uom_symbol: "pcs",
    };
    await withLanguage("pl", () => {
      render(<ProductionStockMovesTable stockMoves={[pcsMove]} />, {
        wrapper: QueryWrapper,
      });

      expect(screen.getByText("12 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/12 pcs/)).not.toBeInTheDocument();
    });
  });

  it("names the shelf a move left and the one it landed on", () => {
    // A consumption move names where it came from (into the run there is
    // no shelf to name); a receipt names where it landed (out of the run
    // there was none). A transfer between shelves would name both.
    const receipt: StockMove = {
      ...move,
      id: "move-2",
      product_template_name: "Jam",
      from_location_id: null,
      from_location_name: null,
      to_location_id: "bb22cc33-dddd-eeee-ffff-001122334455",
      to_location_name: "Output Store",
      lot_id: null,
      lot_code: null,
    };

    render(<ProductionStockMovesTable stockMoves={[move, receipt]} />, {
      wrapper: QueryWrapper,
    });

    expect(screen.getByText("← Cold Storage")).toBeInTheDocument();
    expect(screen.getByText("→ Output Store")).toBeInTheDocument();
    // The identifiers stay in the tooltips, never in the reading surface.
    expect(screen.queryByText(/aa11bb22/)).not.toBeInTheDocument();
    expect(screen.queryByText(/bb22cc33/)).not.toBeInTheDocument();
  });

  it("names a shelf by its path, so two shelves of one name stay two", async () => {
    serveLocations([
      { id: "wa", name: "Warehouse A", parent_id: null },
      { id: "wb", name: "Warehouse B", parent_id: null },
      { id: "shelf-a", name: "Shelf 1", parent_id: "wa" },
      { id: "shelf-b", name: "Shelf 1", parent_id: "wb" },
    ]);
    const transfer: StockMove = {
      ...move,
      from_location_id: "shelf-a",
      from_location_name: "Shelf 1",
      to_location_id: "shelf-b",
      to_location_name: "Shelf 1",
    };

    render(<ProductionStockMovesTable stockMoves={[transfer]} />, {
      wrapper: QueryWrapper,
    });

    expect(
      await screen.findByText("Warehouse A › Shelf 1 → Warehouse B › Shelf 1"),
    ).toBeInTheDocument();
  });

  it("falls back to a label when a named location's row is gone", () => {
    render(
      <ProductionStockMovesTable
        stockMoves={[{ ...move, from_location_name: null }]}
      />,
      { wrapper: QueryWrapper },
    );

    expect(screen.getByText(/← Unknown location/)).toBeInTheDocument();
  });

  it("renders nothing when there are no moves", () => {
    const { container } = render(
      <ProductionStockMovesTable stockMoves={[]} />,
      { wrapper: QueryWrapper },
    );
    expect(container).toBeEmptyDOMElement();
  });
});
