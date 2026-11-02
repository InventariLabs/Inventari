import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RecipeNutritionSection from "./RecipeNutritionSection";

vi.mock("../hooks/useRecipes", () => ({
  useRecipeNutrition: () => ({
    isLoading: false,
    isFetched: true,
    data: null,
  }),
}));

describe("RecipeNutritionSection — a11y", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exposes aria-expanded on the toggle", () => {
    render(<RecipeNutritionSection recipeId="r1" activeServings={2} />);
    const toggle = screen.getByRole("button", { name: /nutrition/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});

describe("RecipeNutritionSection — empty state exit", () => {
  it("offers an edit-recipe shortcut when there is no nutrition data", () => {
    const onEditRecipe = vi.fn();
    render(
      <RecipeNutritionSection
        recipeId="r1"
        activeServings={2}
        onEditRecipe={onEditRecipe}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /nutrition/i }));
    const edit = screen.getByRole("button", { name: /edit/i });
    fireEvent.click(edit);
    expect(onEditRecipe).toHaveBeenCalledTimes(1);
  });

  it("hides the shortcut when no handler is provided", () => {
    render(<RecipeNutritionSection recipeId="r1" activeServings={2} />);
    fireEvent.click(screen.getByRole("button", { name: /nutrition/i }));
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
  });
});
