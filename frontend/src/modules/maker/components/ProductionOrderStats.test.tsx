import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ProductionOrderStats } from "./ProductionOrderStats";
import { withLanguage } from "@/test/mocks/i18n";
import type { ProductionOrder } from "@/modules/maker/types/maker";

// The result's name follows the organization's setting; these screens read
// it through the settings hook, which needs the module and query providers.
vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

/**
 * Nothing rendered this component before, so extracting the six copy-pasted
 * `Card` blocks into a local `StatTile` had no safety net. These pin what the
 * tiles actually put on screen — including the two conditional branches
 * (overproduced vs scrap) that a props mix-up would silently swap.
 */

const baseOrder = {
  id: "po-1",
  status: "DRAFT",
  total_cost: "125.50",
  created_at: "2026-04-02T12:00:00Z",
  production_date: "2026-04-03",
  planned_qty: "10",
  actual_qty: null,
  scrap_qty: null,
  overproduced: false,
  result_per_unit: null,
} as unknown as ProductionOrder;

const order = (over: Partial<ProductionOrder>) =>
  ({ ...baseOrder, ...over }) as ProductionOrder;

describe("ProductionOrderStats", () => {
  it("renders the always-visible tiles", () => {
    render(<ProductionOrderStats order={baseOrder} />);
    // A draft's total cost is empty until the order closes — the tile says
    // so instead of a bare "Total cost" over an em dash.
    expect(screen.getByText("Total cost after closing")).toBeInTheDocument();
    expect(screen.getByText("Created")).toBeInTheDocument();
    expect(screen.getByText("Production date")).toBeInTheDocument();
  });

  it("calls the closed figure a total cost", () => {
    render(<ProductionOrderStats order={order({ status: "COMPLETED" })} />);
    expect(screen.getByText("Total cost")).toBeInTheDocument();
  });

  it("does not promise a cancelled order a closing it will never have", () => {
    // "After closing" on a cancelled order promised a closing that cannot
    // come: the tile waited forever for a number no run would write.
    // DOCUMENTS the r2 rule — dev's tile always said "Total cost", so the
    // assertions hold there too; the discriminating state was the r1
    // branch, where a cancelled order read "Total cost after closing".
    render(<ProductionOrderStats order={order({ status: "CANCELLED" })} />);
    expect(screen.getByText("Total cost")).toBeInTheDocument();
    expect(
      screen.queryByText("Total cost after closing"),
    ).not.toBeInTheDocument();
  });

  it("renders an em dash when there is no production date", () => {
    render(<ProductionOrderStats order={order({ production_date: null })} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("hides the completion tiles until the order is completed", () => {
    render(<ProductionOrderStats order={baseOrder} />);
    expect(screen.queryByText("Actual output")).not.toBeInTheDocument();
  });

  it("shows actual output with the planned quantity as a note", () => {
    render(
      <ProductionOrderStats
        order={order({ status: "COMPLETED", actual_qty: "9" } as never)}
      />,
    );
    expect(screen.getByText("Actual output")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("planned: 10")).toBeInTheDocument();
  });

  it("shows the overproduced tile, not scrap, when overproduced", () => {
    render(
      <ProductionOrderStats
        order={order({
          status: "COMPLETED",
          actual_qty: "12",
          overproduced: true,
          scrap_qty: "2",
        } as never)}
      />,
    );
    expect(screen.getByText("Overproduced")).toBeInTheDocument();
    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(screen.queryByText("Scrap")).not.toBeInTheDocument();
  });

  it("shows the scrap tile when not overproduced", () => {
    render(
      <ProductionOrderStats
        order={order({
          status: "COMPLETED",
          actual_qty: "8",
          overproduced: false,
          scrap_qty: "2",
        } as never)}
      />,
    );
    expect(screen.getByText("Scrap")).toBeInTheDocument();
    expect(screen.queryByText("Overproduced")).not.toBeInTheDocument();
  });

  it("renders the result tile with its per-unit note", () => {
    render(
      <ProductionOrderStats
        order={order({
          status: "COMPLETED",
          actual_qty: "10",
          result_per_unit: "1.50",
        } as never)}
      />,
    );
    // The result is named as every production screen names it, with the
    // line that says what it is.
    expect(screen.getByText("Savings vs shop price")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Shop price minus the cost to make it (PLN 1.50 per unit)",
      ),
    ).toBeInTheDocument();
  });

  // The preview of the same run says "on each kg"; the finished run named
  // no unit at all.
  it("names the output unit in the per-unit result", () => {
    render(
      <ProductionOrderStats
        order={order({
          status: "COMPLETED",
          actual_qty: "10",
          result_per_unit: "10.05",
          output_uom_symbol: "kg",
        } as never)}
      />,
    );
    expect(screen.getByText(/PLN 10\.05 per kg\)/)).toBeInTheDocument();
  });

  it("names a counted unit in the reader's word, not the record's symbol", async () => {
    // "kg" reads the same everywhere; "pcs" inside a Polish sentence did not.
    await withLanguage("pl", () => {
      render(
        <ProductionOrderStats
          order={order({
            status: "COMPLETED",
            actual_qty: "2",
            result_per_unit: "45.68",
            output_uom_symbol: "pcs",
          } as never)}
        />,
      );
      expect(screen.getByText(/za szt\.\)/)).toBeInTheDocument();
      expect(screen.queryByText(/za pcs/)).not.toBeInTheDocument();
    });
  });

  it("writes actual and planned output with the translated unit, once", async () => {
    // The tile printed the raw symbol ("12 pcs") next to a dialog saying
    // "12 szt." on the same page — the unit must come from the same
    // translator the rest of the module asks.
    await withLanguage("pl", () => {
      render(
        <ProductionOrderStats
          order={order({
            status: "COMPLETED",
            actual_qty: "12.000",
            planned_qty: "10.000",
            output_uom_symbol: "pcs",
          } as never)}
        />,
      );

      expect(screen.getByText("12 szt.")).toBeInTheDocument();
      expect(screen.getByText("planowano: 10 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/12\s+pcs/)).not.toBeInTheDocument();
    });
  });

  it("groups thousands like every other screen: 10000 reads as 10 000", async () => {
    // The preview header and this tile used to disagree about the same
    // number; quantities now group thousands everywhere, this tile included.
    await withLanguage("pl", () => {
      render(
        <ProductionOrderStats
          order={order({
            status: "COMPLETED",
            actual_qty: "12000",
            planned_qty: "10000",
            output_uom_symbol: "kg",
          } as never)}
        />,
      );

      expect(screen.getByText("12 000 kg")).toBeInTheDocument();
      expect(screen.getByText("planowano: 10 000 kg")).toBeInTheDocument();
      expect(screen.queryByText(/12000|10000/)).not.toBeInTheDocument();
    });
  });

  it("prints the overproduction delta with its unit and the localized number", async () => {
    // The tile used to print a bare "+2" — no unit, no localization — three
    // lines under the tile this convention was edited in.
    await withLanguage("pl", () => {
      render(
        <ProductionOrderStats
          order={order({
            status: "COMPLETED",
            actual_qty: "12",
            planned_qty: "10",
            overproduced: true,
            scrap_qty: "2",
            output_uom_symbol: "pcs",
          } as never)}
        />,
      );

      expect(screen.getByText("+2 szt.")).toBeInTheDocument();
      expect(screen.queryByText("+2")).not.toBeInTheDocument();
    });
  });

  it("prints scrap with its unit", async () => {
    await withLanguage("pl", () => {
      render(
        <ProductionOrderStats
          order={order({
            status: "COMPLETED",
            actual_qty: "8",
            overproduced: false,
            scrap_qty: "2.000",
            output_uom_symbol: "pcs",
          } as never)}
        />,
      );

      expect(screen.getByText("2 szt.")).toBeInTheDocument();
      expect(screen.queryByText("2.000")).not.toBeInTheDocument();
    });
  });

  describe("a closed run's cost", () => {
    const closed = (lines: unknown[]) =>
      order({
        status: "COMPLETED",
        total_cost: "108.00",
        unit_cost: "18.00",
        actual_qty: "6",
        output_uom_symbol: "pcs",
        lines,
      } as never);
    const priced = {
      child_template_name: "Flour",
      unit_cost_snapshot: "18",
      cost_source: "fifo",
    };
    const unpriced = {
      child_template_name: "Olive Oil",
      unit_cost_snapshot: null,
      cost_source: "none",
    };

    it("names the ingredient the total leaves out", () => {
      render(<ProductionOrderStats order={closed([priced, unpriced])} />);
      const note = screen.getByText(/missing from this total/i);
      expect(note).toHaveTextContent("1 ingredient");
      expect(note).toHaveTextContent("Olive Oil");
    });

    it("keeps a total built from fixed costs when every ingredient is unpriced", () => {
      render(
        <ProductionOrderStats
          order={order({
            status: "COMPLETED",
            total_cost: "60.00",
            unit_cost: "10.00",
            actual_qty: "6",
            output_uom_symbol: "pcs",
            lines: [unpriced],
          } as never)}
        />,
      );
      expect(screen.getByText(/60\.00/)).toBeInTheDocument();
      expect(screen.getByText(/missing from this total/i)).toBeInTheDocument();
    });

    it("does not claim the preview estimated the missing cost", () => {
      render(<ProductionOrderStats order={closed([priced, unpriced])} />);
      expect(
        screen.getByText(/missing from this total/i),
      ).not.toHaveTextContent(/estimated it/i);
    });

    it("says nothing about a gap when every line carried a cost", () => {
      render(<ProductionOrderStats order={closed([priced])} />);
      expect(screen.queryByText(/missing from this total/i)).toBeNull();
    });

    it("states the cost per unit the run's output is counted in", () => {
      render(
        <ProductionOrderStats
          order={{ ...closed([priced]), output_uom_symbol: "kg" }}
        />,
      );
      const line = screen.getByText(/PLN 18\.00 per/);
      expect(line).toHaveTextContent("PLN 18.00 per kg");
      expect(line).not.toHaveTextContent(/produced/i);
    });
  });
});
