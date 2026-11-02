import { describe, it, expect } from "vitest";
import { fireEvent } from "@testing-library/react";
import { render, screen } from "@testing-library/react";
import { RecipeHeroCard } from "./RecipeHeroCard";
import en from "@/modules/recipes/i18n/en.json";
import type { Recipe } from "@/modules/recipes/types/core";
import { withLanguage } from "@/test/mocks/i18n";

const t = (key: string, opts?: Record<string, unknown>) => {
  const path = key.replace("recipes:", "").split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = en;
  for (const part of path) value = value?.[part];
  if (typeof value !== "string") return key;
  return value.replace(/\{\{\w+\}\}/g, (m) =>
    String(opts?.[m.slice(2, -2)] ?? m),
  );
};

const baseRecipe: Recipe = {
  id: "r1",
  organization_id: "o1",
  created_by: "u1",
  name: "Test Recipe",
  description: null,
  instructions: null,
  servings: 2,
  prep_time_minutes: null,
  image_url: null,
  source_url: null,
  tags: null,
  is_favorite: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ingredients: [],
  allergens: [],
};

const renderCard = (recipe: Recipe, nutritionCalories?: number) =>
  render(
    <RecipeHeroCard
      recipe={recipe}
      nutritionCalories={nutritionCalories}
      uploadImageMutation={{ isPending: false }}
      deleteImageMutation={{ isPending: false }}
      onImageUpload={vi.fn()}
      onDeleteImage={vi.fn()}
      onEditRequest={vi.fn()}
      tagInput=""
      onTagInputChange={vi.fn()}
      onAddTag={vi.fn()}
      t={t}
    />,
  );

describe("RecipeHeroCard — allergen badges", () => {
  it("shows allergen badges with translated names", () => {
    renderCard({
      ...baseRecipe,
      allergens: ["milk", "gluten"],
    });
    expect(screen.getByText(/allergens:/i)).toBeInTheDocument();
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("Gluten")).toBeInTheDocument();
  });

  it("renders no allergen row when the recipe has none", () => {
    renderCard(baseRecipe);
    expect(screen.queryByText(/allergens:/i)).not.toBeInTheDocument();
  });

  it("does not let an empty allergen list read as allergen-free", () => {
    renderCard(baseRecipe);
    expect(
      screen.getByText(/suggested from ingredient names.*may be incomplete/i),
    ).toBeInTheDocument();
  });

  it("uses the warning badge variant so pills stay readable in dark mode", () => {
    renderCard({ ...baseRecipe, allergens: ["milk"] });
    const pill = screen.getByText("Milk");
    // Badge variant="warning" — explicit dark-mode colors instead of the
    // buggy `bg-amber-100 text-amber-900` (contrast 1:1 in dark mode).
    // The theme-aware `text-on-warning` token replaced the
    // `dark:text-amber-400` override.
    expect(pill).toHaveClass("bg-amber-100");
    expect(pill).toHaveClass("text-on-warning");
    expect(pill).not.toHaveClass("text-amber-900");
  });
});

describe("RecipeHeroCard — the calorie figure", () => {
  /**
   * `Math.round` answers in JavaScript, not in any language: a big batch's
   * calories printed as "1194713 kcal" in every one of the five.
   */
  it("writes the calories with the reader's digit grouping", async () => {
    await withLanguage("pl", () => {
      renderCard(baseRecipe, 1194713);

      expect(screen.getByText(/^1\s194\s713$/)).toBeInTheDocument();
      expect(screen.queryByText("1194713")).not.toBeInTheDocument();
    });
  });
});

describe("RecipeHeroCard — the cover", () => {
  it("gives the picture a photo's shape rather than a strip", () => {
    renderCard({ ...baseRecipe, image_url: "/uploads/recipes/r1/cover.jpg" });

    // A fixed 176px band on a wide card is nearer 3:1 than anything a camera
    // produces, so every cover was shown as a slice through its middle —
    // which is how one wide picture came to look like two side by side.
    const cover = screen.getByAltText("Test Recipe");
    expect(cover).toHaveClass("aspect-[16/9]");
    expect(cover).not.toHaveClass("h-44");
  });

  it("says so when the picture will not load, instead of leaving a frame", () => {
    renderCard({ ...baseRecipe, image_url: "/uploads/recipes/r1/cover.jpg" });

    fireEvent.error(screen.getByAltText("Test Recipe"));

    expect(screen.queryByAltText("Test Recipe")).not.toBeInTheDocument();
    expect(screen.getByText(en.image.unavailable)).toBeInTheDocument();
    // And the way to put one there is offered in the same place.
    expect(
      screen.getByRole("button", { name: en.image.upload }),
    ).toBeInTheDocument();
  });

  it("offers no delete button for a picture that is not there", () => {
    renderCard({ ...baseRecipe, image_url: "/uploads/recipes/r1/cover.jpg" });
    expect(
      screen.getByRole("button", { name: en.image.delete }),
    ).toBeInTheDocument();

    fireEvent.error(screen.getByAltText("Test Recipe"));

    expect(
      screen.queryByRole("button", { name: en.image.delete }),
    ).not.toBeInTheDocument();
  });
});
