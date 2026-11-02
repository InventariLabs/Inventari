import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RecipeCostSection from "./RecipeCostSection";

vi.mock("../hooks/useRecipes", () => ({
  useRecipeCost: () => ({
    isLoading: false,
    isFetched: true,
    data: {
      recipe_id: "r1",
      servings: 2,
      estimated_cost: null,
      currency: null,
      cost_coverage: 0,
      mixed_currencies: false,
      missing_cost_ingredients: [],
      ingredients: [],
    },
  }),
}));

describe("RecipeCostSection — a11y", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exposes aria-expanded on the toggle", () => {
    render(<RecipeCostSection recipeId="r1" activeServings={2} />);
    const toggle = screen.getByRole("button", { name: /cost/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});

describe("RecipeCostSection — empty state exit", () => {
  it("offers an edit-recipe shortcut when there is no price data", () => {
    const onEditRecipe = vi.fn();
    render(
      <RecipeCostSection
        recipeId="r1"
        activeServings={2}
        onEditRecipe={onEditRecipe}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /cost/i }));
    const edit = screen.getByRole("button", { name: /edit/i });
    fireEvent.click(edit);
    expect(onEditRecipe).toHaveBeenCalledTimes(1);
  });

  it("hides the shortcut when no handler is provided", () => {
    render(<RecipeCostSection recipeId="r1" activeServings={2} />);
    fireEvent.click(screen.getByRole("button", { name: /cost/i }));
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
  });
});
