import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HistoryTab } from "./HistoryTab";
import type { MakerRecipe } from "@/modules/maker/types/maker";

const read = vi.hoisted(() => ({
  failed: false,
  items: [] as unknown[],
  refetch: vi.fn(),
}));

// The result's name follows the organization's setting; these screens read
// it through the settings hook, which needs the module and query providers.
vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useProductionOrders: () => ({
    data: read.failed
      ? undefined
      : { items: read.items, total: read.items.length },
    isLoading: false,
    isError: read.failed,
    refetch: read.refetch,
  }),
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

const recipe = { id: "r-1", output_template_id: "tpl-1" } as MakerRecipe;

function renderTab() {
  return render(
    <MemoryRouter>
      <HistoryTab recipe={recipe} />
    </MemoryRouter>,
  );
}

describe("HistoryTab", () => {
  afterEach(() => {
    read.failed = false;
    read.items = [];
    read.refetch.mockClear();
  });

  it("says the recipe has no runs yet when the list came back empty", () => {
    renderTab();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByText("No production runs for this BOM yet."),
    ).toBeInTheDocument();
  });

  it("does not claim the recipe has no runs when the read failed", () => {
    read.failed = true;
    renderTab();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(read.refetch).toHaveBeenCalledTimes(1);
  });

  it("writes the result's definition where the phone's cards show it too", () => {
    // The definition was a hover title on the desktop table's heading; the
    // phone's cards, which hide that table, said only "Savings vs shop
    // price per unit" with nothing to say what that is.
    read.items = [
      {
        id: "ord-1",
        status: "COMPLETED",
        planned_qty: "5",
        actual_qty: "5",
        output_uom_symbol: "kg",
        unit_cost_snapshot: "2",
        result_per_unit: "1.5",
        total_cost: "10",
        created_at: "2026-01-01T00:00:00Z",
        completed_at: "2026-01-02T00:00:00Z",
      },
    ];
    renderTab();

    expect(
      screen.getByText(
        "Savings vs shop price: Shop price minus the cost to make it",
      ),
    ).toBeInTheDocument();
    const heading = screen.getByRole("columnheader", {
      name: /Savings vs shop price per unit/,
    });
    expect(heading).not.toHaveAttribute("title");
    expect(heading).toHaveAccessibleDescription(
      "Savings vs shop price: Shop price minus the cost to make it",
    );
  });
});
