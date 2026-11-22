import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RecipeDeleteConfirm } from "./RecipeDeleteConfirm";
import type { RecipePlannedMeal } from "../types/mealplans";

const mocks = vi.hoisted(() => ({ useRecipePlannedMeals: vi.fn() }));

vi.mock("../hooks/useRecipes", () => ({
  useRecipePlannedMeals: mocks.useRecipePlannedMeals,
}));

const meal = (
  day: number,
  slot: RecipePlannedMeal["slot"],
): RecipePlannedMeal => ({
  plan_id: "p1",
  plan_name: "Week plan",
  date: `2026-11-${String(day).padStart(2, "0")}`,
  slot,
});

function open(onConfirm = vi.fn()) {
  render(
    <RecipeDeleteConfirm
      recipeId="r1"
      name="Garlic bread"
      onConfirm={onConfirm}
      onCancel={vi.fn()}
    />,
  );
  return onConfirm;
}

describe("RecipeDeleteConfirm", () => {
  beforeEach(() => mocks.useRecipePlannedMeals.mockReset());

  it("names the plan, the day and the meal the delete will empty", () => {
    mocks.useRecipePlannedMeals.mockReturnValue({
      data: [meal(23, "BREAKFAST")],
    });
    open();
    const text = screen.getByRole("alertdialog").textContent ?? "";
    expect(text).toMatch(/Week plan, .*23.*2026, Breakfast/);
    expect(text).toContain("those meals will be emptied");
  });

  it("counts the meals beyond the five it names", () => {
    mocks.useRecipePlannedMeals.mockReturnValue({
      data: [20, 21, 22, 23, 24, 25, 26].map((d) => meal(d, "LUNCH")),
    });
    open();
    expect(screen.getByRole("alertdialog").textContent).toContain("+2 more");
  });

  it("says nothing of plans for a recipe that is in none", () => {
    mocks.useRecipePlannedMeals.mockReturnValue({ data: [] });
    open();
    const text = screen.getByRole("alertdialog").textContent ?? "";
    expect(text).toContain("Delete recipe");
    expect(text).not.toContain("Meal plans");
    expect(text).not.toContain("planned in");
  });

  it("warns in general terms while the plans are unknown", () => {
    mocks.useRecipePlannedMeals.mockReturnValue({ data: undefined });
    open();
    expect(screen.getByRole("alertdialog").textContent).toContain(
      "Meal plans that include a deleted recipe lose those meals",
    );
  });

  it("deletes on confirm", () => {
    mocks.useRecipePlannedMeals.mockReturnValue({ data: [] });
    const onConfirm = open();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
