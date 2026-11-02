import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProductionTable } from "./ProductionTable";
import type { ProductionOrder } from "@/modules/maker/types/maker";

// The result's name follows the organization's setting; these screens read
// it through the settings hook, which needs the module and query providers.
vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

const order: ProductionOrder = {
  id: "ord-1",
  organization_id: "org-1",
  output_template_id: "tpl-1",
  output_template_name: "Jar",
  recipe_id: null,
  number: null,
  planned_qty: "5",
  actual_qty: null,
  overproduced: false,
  scrap_qty: null,
  output_location_id: "loc-1",
  status: "DRAFT",
  total_cost: null,
  production_date: null,
  notes: null,
  created_by: null,
  completed_by: null,
  created_at: "2026-01-01T00:00:00Z",
  completed_at: null,
  cancel_reason: null,
  produced_item_id: null,
  produced_item_name: null,
  unit_cost_snapshot: null,
  reference_price_snapshot: null,
  result_per_unit: null,
  result_per_batch: null,
  lines: [],
};

/**
 * The row opened its order from a `<tr onClick>`; the link in the name was
 * the keyboard's only way in and the row click was a duplicate that ate
 * middle clicks and "open in a new tab". The link is the only way in now,
 * as it is on the equipment and inventory lists.
 */
describe("ProductionTable — the row opens through a link", () => {
  const renderRouted = (orders: ProductionOrder[]) =>
    render(
      <MemoryRouter initialEntries={["/maker/production"]}>
        <Routes>
          <Route
            path="/maker/production"
            element={
              <ProductionTable
                orders={orders}
                sort="newest"
                isDuplicating={false}
              />
            }
          />
          <Route path="/maker/production/:id" element={<p>ORDER DETAIL</p>} />
        </Routes>
      </MemoryRouter>,
    );

  it("gives every row one link named after its product", () => {
    renderRouted([
      order,
      { ...order, id: "ord-2", output_template_name: "Bottle" },
    ]);

    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Jar" })).toHaveAttribute(
      "href",
      "/maker/production/ord-1",
    );
  });

  it("does not navigate when the click lands on the row, not the link", () => {
    renderRouted([order]);

    fireEvent.click(screen.getAllByRole("row")[1]);

    expect(screen.queryByText("ORDER DETAIL")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Jar" })).toBeInTheDocument();
  });
});

describe("ProductionTable — the result column", () => {
  it("says what the result is under the table, not in a hover title", () => {
    render(
      <MemoryRouter>
        <ProductionTable orders={[order]} sort="newest" isDuplicating={false} />
      </MemoryRouter>,
    );

    const heading = screen.getByRole("columnheader", {
      name: "Savings vs shop price",
    });
    expect(heading).not.toHaveAttribute("title");
    expect(
      screen.getByText(
        "Savings vs shop price: Shop price minus the cost to make it",
      ),
    ).toBeInTheDocument();
    expect(heading).toHaveAccessibleDescription(
      "Savings vs shop price: Shop price minus the cost to make it",
    );
  });
});
