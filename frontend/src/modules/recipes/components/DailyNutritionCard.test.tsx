import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DailyNutritionCard } from "./DailyNutritionCard";

const day = (generic_values: boolean, date = "2026-11-02") => ({
  date,
  calories_kcal: 700,
  protein_g: 24,
  fat_g: 10,
  carbs_g: 130,
  coverage: 1,
  generic_values,
});

describe("DailyNutritionCard — where the totals come from", () => {
  it("says the totals add up estimates from labels or Open Food Facts", () => {
    render(<DailyNutritionCard days={[day(false)]} />);
    expect(
      screen.getByText(/add up the estimates.*Open Food Facts/),
    ).toBeVisible();
    expect(screen.queryByText(/generic values/)).not.toBeInTheDocument();
  });

  it("says so when any day used generic values", () => {
    render(<DailyNutritionCard days={[day(false), day(true, "2026-11-03")]} />);
    expect(screen.getByText(/Some use generic values/)).toBeVisible();
  });
});
