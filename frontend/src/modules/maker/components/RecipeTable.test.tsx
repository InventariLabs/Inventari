import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RecipeTable } from "./RecipeTable";
import type { RecipeCatalogItem } from "@/modules/maker/types/maker";

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));
vi.mock("@/modules/maker/components/AvailabilityBadge", () => ({
  AvailabilityBadge: () => <span data-testid="availability" />,
}));

const baseRecipe: RecipeCatalogItem = {
  id: "recipe-1",
  output_template_id: "tpl-1",
  name: "Granola Bars",
  output_template_name: "Granola Bars 500g",
  batch_yield_qty: "1",
  is_default: false,
  ingredient_count: 3,
  unit_cost: "5.00",
  uncosted_ingredients: 0,
  estimated_uncosted_ingredients: 0,
  reference_price: null,
  result: null,
  reference_direction: null,
  stock_qty: null,
  last_produced_at: null,
};

function renderTable(recipes: RecipeCatalogItem[]) {
  return render(
    <MemoryRouter>
      <RecipeTable recipes={recipes} sort="newest" />
    </MemoryRouter>,
  );
}

/**
 * The row opened its recipe from a `<tr onClick>`; the link in the name was
 * the keyboard's only way in and the row click was a duplicate that ate
 * middle clicks and "open in a new tab". The link is the only way in now,
 * as it is on the equipment and inventory lists.
 */
describe("RecipeTable — the row opens through a link", () => {
  const renderRouted = (recipes: RecipeCatalogItem[]) =>
    render(
      <MemoryRouter initialEntries={["/maker/recipes"]}>
        <Routes>
          <Route
            path="/maker/recipes"
            element={<RecipeTable recipes={recipes} sort="newest" />}
          />
          <Route path="/maker/recipes/:id" element={<p>RECIPE DETAIL</p>} />
        </Routes>
      </MemoryRouter>,
    );

  it("gives every row one link named after its recipe", () => {
    renderRouted([
      baseRecipe,
      { ...baseRecipe, id: "recipe-2", name: "Muesli" },
    ]);

    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Granola Bars" })).toHaveAttribute(
      "href",
      "/maker/recipes/recipe-1",
    );
  });

  it("does not navigate when the click lands on the row, not the link", () => {
    renderRouted([baseRecipe]);

    fireEvent.click(screen.getByText("3 ingredients"));

    expect(screen.queryByText("RECIPE DETAIL")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Granola Bars" }),
    ).toBeInTheDocument();
  });
});

describe("RecipeTable — the unit-cost column names its number", () => {
  it("shows the estimate a never-run recipe has, under its own label", () => {
    // The table kept printing a dash for every recipe without a run while
    // the card beside it showed the number — the list view answered the
    // catalog's question with less than the card view did.
    renderTable([
      {
        ...baseRecipe,
        unit_cost: null,
        estimated_unit_cost: "2.50",
        estimated_uncosted_ingredients: 0,
      },
    ]);

    expect(screen.getByText("Estimated unit cost")).toBeInTheDocument();
    expect(screen.getByText("PLN 2.50")).toBeInTheDocument();
    expect(screen.queryByText(/after last run/i)).not.toBeInTheDocument();
  });

  it("names the run's figure as the run's", () => {
    renderTable([baseRecipe]);

    expect(screen.getByText("Unit cost after last run")).toBeInTheDocument();
    expect(screen.getByText("PLN 5.00")).toBeInTheDocument();
  });

  it("keeps the dash where there is nothing to compute from", () => {
    renderTable([
      {
        ...baseRecipe,
        unit_cost: null,
        estimated_unit_cost: null,
      },
    ]);

    // Once as the column heading, once as the row's own label — the row
    // says "the system does not know" under the same word the column does.
    expect(screen.getAllByText("Unit cost").length).toBeGreaterThanOrEqual(2);
  });
});

describe("RecipeTable — the result column", () => {
  it("is headed Margin when no row carries the direction yet", () => {
    // A new organization's result is a margin, so the heading does not
    // name savings before the server has said which one it is.
    renderTable([baseRecipe]);

    expect(
      screen.getByRole("columnheader", { name: "Margin" }),
    ).toBeInTheDocument();
  });

  it("says what the result is under the table, not in a hover title", () => {
    renderTable([{ ...baseRecipe, reference_direction: "SAVINGS" }]);

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

  it("follows the direction the rows carry", () => {
    renderTable([{ ...baseRecipe, reference_direction: "SAVINGS" }]);

    expect(
      screen.getByRole("columnheader", { name: "Savings vs shop price" }),
    ).toBeInTheDocument();
  });
});
