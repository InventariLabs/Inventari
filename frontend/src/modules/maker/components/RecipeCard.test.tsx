import { describe, it, expect, vi, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RecipeCard } from "./RecipeCard";
import { withLanguage } from "@/test/mocks/i18n";
import type { RecipeCatalogItem } from "@/modules/maker/types/maker";

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerRecipeAvailability: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
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
  reference_price: "8.00",
  result: "3.00",
  reference_direction: "SAVINGS",
  stock_qty: null,
  last_produced_at: null,
};

function renderCard(recipe: RecipeCatalogItem, onProduce = vi.fn()) {
  render(
    <MemoryRouter>
      <RecipeCard recipe={recipe} onProduce={onProduce} />
    </MemoryRouter>,
  );
  return onProduce;
}

afterEach(() => {
  signOut();
});

describe("RecipeCard — the unit-cost line names its number", () => {
  it("says after last run when the recipe has one", () => {
    renderCard(baseRecipe);
    expect(screen.getByText("Unit cost after last run")).toBeInTheDocument();
    expect(screen.queryByText("Estimated unit cost")).not.toBeInTheDocument();
  });

  it("shows today's estimate, named, when no run ever closed", () => {
    renderCard({
      ...baseRecipe,
      unit_cost: null,
      uncosted_ingredients: 0,
      estimated_unit_cost: "2.50",
      estimated_uncosted_ingredients: 0,
      result: null,
    });

    expect(screen.getByText("Estimated unit cost")).toBeInTheDocument();
    expect(screen.getByText("PLN 2.50")).toBeInTheDocument();
    expect(
      screen.queryByText("Unit cost after last run"),
    ).not.toBeInTheDocument();
  });

  it("does not blame the last run for an estimate's missing rates", () => {
    // An estimate with an unpriced ingredient borrowed the run's warning
    // sentence and spoke of "the last run" — a run that never happened.
    renderCard({
      ...baseRecipe,
      unit_cost: null,
      uncosted_ingredients: 0,
      estimated_unit_cost: "2.50",
      estimated_uncosted_ingredients: 1,
      result: null,
    });

    expect(
      screen.getByText(
        "1 ingredient in this estimate has no purchase cost recorded.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTitle(/in the last run/)).not.toBeInTheDocument();
  });

  it("keeps the bare label and the dash when there is nothing to compute from", () => {
    renderCard({
      ...baseRecipe,
      unit_cost: null,
      uncosted_ingredients: 0,
      estimated_unit_cost: null,
      result: null,
    });

    expect(screen.getByText("Unit cost")).toBeInTheDocument();
  });
});

describe("RecipeCard result display", () => {
  it("renders the savings label for SAVINGS direction", () => {
    renderCard(baseRecipe);
    const resultRow = screen.getByTestId("maker-recipe-card-result");
    expect(resultRow).toHaveTextContent("Savings");
    expect(resultRow).toHaveTextContent("PLN 3.00");
  });

  it("renders the margin label for MARGIN direction", () => {
    renderCard({
      ...baseRecipe,
      result: "1.25",
      reference_direction: "MARGIN",
    });
    const resultRow = screen.getByTestId("maker-recipe-card-result");
    expect(resultRow).toHaveTextContent("Margin");
    expect(resultRow).toHaveTextContent("PLN 1.25");
  });

  it("renders nothing when result is null", () => {
    renderCard({ ...baseRecipe, result: null, reference_direction: null });
    expect(
      screen.queryByTestId("maker-recipe-card-result"),
    ).not.toBeInTheDocument();
  });

  it("passes the recipe to onProduce", () => {
    const onProduce = renderCard(baseRecipe);
    fireEvent.click(screen.getByRole("button", { name: "Produce" }));
    expect(onProduce).toHaveBeenCalledWith(baseRecipe);
  });
});

describe("RecipeCard without ingredients", () => {
  const emptyRecipe: RecipeCatalogItem = {
    ...baseRecipe,
    ingredient_count: 0,
    unit_cost: null,
    result: null,
  };

  it("offers adding ingredients instead of producing", () => {
    // Adding ingredients writes the formula — the manager's account.
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderCard(emptyRecipe);
    expect(
      screen.getByTestId("maker-recipe-card-add-ingredients"),
    ).toHaveTextContent("Add ingredients");
    expect(
      screen.queryByRole("button", { name: "Produce" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the produce action once the formula has a line", () => {
    // The floor keeps its action: producing is maker:write, which the
    // ordinary member holds.
    signInWith(["maker:read", "maker:write"]);
    renderCard({ ...emptyRecipe, ingredient_count: 1 });
    expect(screen.getByRole("button", { name: "Produce" })).toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-recipe-card-add-ingredients"),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeCard stock figure", () => {
  it("writes the stock number the reader's language writes, separator included", async () => {
    // The catalog's stock figure came raw off the decimal column: an
    // American point in a Polish interface ("1234.5"). The module has no
    // unit for this field, but the number still follows the one convention.
    await withLanguage("pl", () => {
      renderCard({ ...baseRecipe, stock_qty: "1234.5000" });

      expect(screen.getByText("1234,5")).toBeInTheDocument();
      expect(screen.queryByText("1234.5")).not.toBeInTheDocument();
      expect(screen.queryByText(/1[\s ]234/)).not.toBeInTheDocument();
    });
  });
});

describe("RecipeCard thumbnail", () => {
  it("shows the output product's picture when the product has one", () => {
    renderCard({
      ...baseRecipe,
      output_template_image_url: "https://img.example/granola.png",
    });
    // alt="" — the name beside it already says what it is; the image is
    // presentation, so the role list has no "img" entry.
    const img = screen.getByAltText("");
    expect(img).toHaveAttribute("src", "https://img.example/granola.png");
  });

  it("stays with the flask icon when the product has no picture", () => {
    renderCard(baseRecipe);
    expect(screen.queryByAltText("")).not.toBeInTheDocument();
  });
});
