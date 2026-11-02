import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SuggestedRecipes } from "./SuggestedRecipes";
import type { SuggestedRecipe } from "@/modules/recipes/types/mealplans";

const t = (key: string) => key;

const suggestion = (
  overrides: Partial<SuggestedRecipe> = {},
): SuggestedRecipe => ({
  recipe_id: "r1",
  name: "Pancakes",
  image_url: null,
  prep_time_minutes: null,
  availability_pct: 0.8,
  ingredients_available: 4,
  ingredients_total: 5,
  expiry_urgency_score: 0,
  score: 0.5,
  ...overrides,
});

describe("SuggestedRecipes coverage badge", () => {
  it("writes the ratio the recipe cards write, not a bare percentage", () => {
    // This used to render a percent icon and the number alone — "⁒ 100" —
    // with no title and no accessible name, so a screen reader announced
    // "100" and nothing said what of.
    render(
      <SuggestedRecipes
        suggestions={[suggestion()]}
        isLoading={false}
        onSelect={vi.fn()}
        t={t}
      />,
    );

    expect(screen.getByText("4/5 in stock")).toBeInTheDocument();
    expect(screen.getByText("4 of 5 in stock")).toBeInTheDocument();
    expect(screen.queryByText("80")).toBeNull();
  });

  it("writes no coverage for a suggestion with nothing to check", () => {
    render(
      <SuggestedRecipes
        suggestions={[
          suggestion({ ingredients_available: 0, ingredients_total: 0 }),
        ]}
        isLoading={false}
        onSelect={vi.fn()}
        t={t}
      />,
    );

    expect(screen.queryByText(/in stock/)).toBeNull();
  });
});
