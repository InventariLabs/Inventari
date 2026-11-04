import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import NutritionCard from "./NutritionCard";
import type { RecipeNutrition } from "@/modules/recipes/types/nutrition";

const nutrition = (coverage: number): RecipeNutrition => ({
  warnings: [],
  scale: 1,
  recipe_id: "r1",
  servings: 2,
  per_serving: {
    calories_kcal: 500,
    protein_g: 20,
    fat_g: 10,
    carbs_g: 60,
    fiber_g: 5,
    sugar_g: 2,
    salt_g: 1,
  },
  total: {
    calories_kcal: 1000,
    protein_g: 40,
    fat_g: 20,
    carbs_g: 120,
    fiber_g: 10,
    sugar_g: 4,
    salt_g: 2,
  },
  ingredients: [],
  coverage,
  missing_nutrition: [],
  generic_values: false,
});

describe("NutritionCard — empty state exit", () => {
  it("offers an edit-recipe shortcut when coverage is low", () => {
    const onEditRecipe = vi.fn();
    render(
      <NutritionCard
        data={nutrition(0.25)}
        servings={2}
        onEditRecipe={onEditRecipe}
      />,
    );
    const edit = screen.getByRole("button", { name: /edit/i });
    fireEvent.click(edit);
    expect(onEditRecipe).toHaveBeenCalledTimes(1);
  });

  it("hides the shortcut when coverage is full", () => {
    render(
      <NutritionCard data={nutrition(1)} servings={2} onEditRecipe={vi.fn()} />,
    );
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
  });
});

describe("NutritionCard — where the values come from", () => {
  it("says it is an estimate from product labels or Open Food Facts", () => {
    render(<NutritionCard data={nutrition(1)} servings={2} />);
    expect(
      screen.getByText(/estimate.*labels or Open Food Facts/i),
    ).toBeVisible();
  });

  it("says so when generic values were used", () => {
    render(
      <NutritionCard
        data={{ ...nutrition(1), generic_values: true }}
        servings={2}
      />,
    );
    expect(screen.getByText(/Some use generic values/)).toBeVisible();
  });
});

describe("NutritionCard — a nutrient nobody measured", () => {
  const partial: RecipeNutrition = {
    ...nutrition(0.2),
    per_serving: {
      calories_kcal: 248,
      carbs_g: null,
      fat_g: 5.4,
      protein_g: 46.5,
      fiber_g: 1,
      sugar_g: null,
      salt_g: null,
    },
  };

  it("prints a dash for it, never 0 g", () => {
    render(<NutritionCard data={partial} servings={1} />);
    const carbs = screen.getByText("Carbs").parentElement;
    expect(carbs).toHaveTextContent("–");
    expect(carbs).not.toHaveTextContent("0.0g");
    expect(screen.getByText("Sugar").parentElement).toHaveTextContent("–");
    expect(screen.getByText("Protein").parentElement).toHaveTextContent(
      "46.5g",
    );
  });

  it("keeps a zero the ingredients really measured", () => {
    render(
      <NutritionCard
        data={{
          ...nutrition(1),
          per_serving: { ...nutrition(1).per_serving, carbs_g: 0 },
        }}
        servings={1}
      />,
    );
    expect(screen.getByText("Carbs").parentElement).toHaveTextContent("0.0g");
  });
});
