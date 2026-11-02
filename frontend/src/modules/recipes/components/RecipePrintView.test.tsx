import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RecipePrintView } from "./RecipePrintView";
import { withLanguage } from "@/test/mocks/i18n";
import type { Recipe } from "@/modules/recipes/types/core";
import type {
  RecipeNutrition,
  RecipeCost,
} from "@/modules/recipes/types/nutrition";

vi.mock("@/store/authStore", () => ({
  useAuthStore: (fn: (s: { user: { organization_name: string } }) => string) =>
    fn({ user: { organization_name: "Test Kitchen" } }),
}));

const baseRecipe: Recipe = {
  id: "r1",
  organization_id: "o1",
  created_by: "u1",
  name: "Pancakes",
  description: null,
  instructions: "1. Mix. 2. Fry.",
  servings: 4,
  prep_time_minutes: 15,
  image_url: null,
  source_url: null,
  tags: null,
  is_favorite: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ingredients: [
    {
      id: "i1",
      recipe_id: "r1",
      name: "Flour",
      template_id: null,
      ingredient_group_name: null,
      quantity: "200",
      uom_id: null,
      uom_symbol: "g",
      is_optional: false,
      is_spice: false,
      picking_skip: null,
      sort_order: 0,
      calories_kcal_per_100g: null,
      display_text: null,
      original_quantity: null,
      original_unit_text: null,
      price: null,
      price_uom_id: null,
      price_currency: null,
      allergens: ["gluten"],
    },
    {
      id: "i2",
      recipe_id: "r1",
      name: "Milk",
      template_id: null,
      ingredient_group_name: null,
      quantity: "300",
      uom_id: null,
      uom_symbol: "ml",
      is_optional: false,
      is_spice: false,
      picking_skip: null,
      sort_order: 1,
      calories_kcal_per_100g: null,
      display_text: null,
      original_quantity: null,
      original_unit_text: null,
      price: null,
      price_uom_id: null,
      price_currency: null,
      allergens: ["milk"],
    },
  ],
  allergens: ["gluten", "milk"],
};

const nutrition: RecipeNutrition = {
  warnings: [],
  scale: 1,
  recipe_id: "r1",
  servings: 4,
  per_serving: {
    calories_kcal: 250,
    protein_g: 8,
    fat_g: 5,
    carbs_g: 40,
    fiber_g: 2,
    sugar_g: 4,
    salt_g: 0.5,
  },
  total: {
    calories_kcal: 1000,
    protein_g: 32,
    fat_g: 20,
    carbs_g: 160,
    fiber_g: 8,
    sugar_g: 16,
    salt_g: 2,
  },
  ingredients: [],
  coverage: 100,
  missing_nutrition: [],
  generic_values: false,
};

const cost: RecipeCost = {
  recipe_id: "r1",
  enabled: true,
  servings: 4,
  estimated_cost: 12,
  currency: "PLN",
  cost_coverage: 100,
  mixed_currencies: false,
  missing_cost_ingredients: [],
  ingredients: [],
};

describe("RecipePrintView — recipe card", () => {
  it("scales ingredient quantities to the printed servings", () => {
    render(
      <RecipePrintView
        recipe={baseRecipe}
        servings={8}
        nutrition={nutrition}
        cost={cost}
      />,
    );
    // 200g flour at 4 servings → 400g at 8; 300ml → 600ml
    expect(screen.getByText(/400\s*g/)).toBeInTheDocument();
    expect(screen.getByText(/600\s*ml/)).toBeInTheDocument();
  });

  it("shows recipe name, org, allergens, nutrition and cost per serving", () => {
    render(
      <RecipePrintView
        recipe={baseRecipe}
        servings={4}
        nutrition={nutrition}
        cost={cost}
      />,
    );
    expect(screen.getByText("Pancakes")).toBeInTheDocument();
    expect(screen.getByText("Test Kitchen")).toBeInTheDocument();
    expect(screen.getByText(/Gluten,\s*Milk/)).toBeInTheDocument();
    expect(screen.getByText(/250\s*kcal/)).toBeInTheDocument();
    expect(screen.getByText(/Estimated cost:/)).toBeInTheDocument();
  });

  /**
   * The macros on paper were rounded to whole grams while the screen writes
   * them through the shared formatter ("1,1 g") — one number in two shapes on
   * one path. The printout is read like any other screen, as its own quantity
   * helper already says.
   */
  it("writes the macros as the screen does, not as whole grams", async () => {
    await withLanguage("pl", () => {
      render(
        <RecipePrintView
          recipe={baseRecipe}
          servings={4}
          nutrition={nutrition}
          cost={cost}
        />,
      );

      expect(screen.getByText(/^Białko: 8,0g$/)).toBeInTheDocument();
      expect(screen.queryByText(/^Białko: 8g$/)).not.toBeInTheDocument();
    });
  });

  it("says on paper when the nutrition covers only part of the ingredients", () => {
    render(
      <RecipePrintView
        recipe={baseRecipe}
        servings={4}
        nutrition={{ ...nutrition, coverage: 0.6 }}
      />,
    );
    expect(
      screen.getByText("Nutrition data available for 60% of ingredients only"),
    ).toBeInTheDocument();
  });

  it("prints no caveat when the nutrition covers the recipe", () => {
    render(
      <RecipePrintView
        recipe={baseRecipe}
        servings={4}
        nutrition={{ ...nutrition, coverage: 1 }}
      />,
    );
    expect(screen.queryByTestId("print-nutrition-partial")).toBeNull();
  });

  it("carries the allergen and nutrition caveats on the paper", () => {
    render(
      <RecipePrintView
        recipe={baseRecipe}
        servings={4}
        nutrition={nutrition}
      />,
    );
    expect(screen.getByTestId("print-allergen-note")).toHaveTextContent(
      "Suggested from ingredient names; may be incomplete. Check the label of each product used.",
    );
    expect(screen.getByTestId("print-nutrition-estimate")).toHaveTextContent(
      /estimate.*labels or Open Food Facts/i,
    );
  });

  it("says on the paper when generic values went into the estimate", () => {
    render(
      <RecipePrintView
        recipe={baseRecipe}
        servings={4}
        nutrition={{ ...nutrition, generic_values: true }}
      />,
    );
    expect(screen.getByTestId("print-nutrition-estimate")).toHaveTextContent(
      /Some use generic values/,
    );
  });

  it("does not let a recipe with no allergen marked read as allergen-free", () => {
    render(
      <RecipePrintView
        recipe={{ ...baseRecipe, allergens: [] }}
        servings={4}
      />,
    );
    expect(screen.getByTestId("print-allergen-note")).toHaveTextContent(
      /No allergens marked.*suggested from ingredient names.*incomplete/,
    );
  });

  it("hides nutrition/cost sections when data is unavailable", () => {
    render(<RecipePrintView recipe={baseRecipe} servings={4} />);
    expect(screen.queryByText(/250\s*kcal/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Estimated cost:/)).not.toBeInTheDocument();
  });

  it("shows the servings count in the header line (plural key with count)", () => {
    render(<RecipePrintView recipe={baseRecipe} servings={8} />);
    expect(screen.getByText(/8 servings/)).toBeInTheDocument();
  });
});
