import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MealPlanCalendar } from "./MealPlanCalendar";
import type { MealPlan } from "@/modules/recipes/types/mealplans";
import { tFor, withLanguage } from "@/test/mocks/i18n";

function mealPlan(): MealPlan {
  return {
    id: "mp1",
    name: null,
    // 2026-08-14 is a Friday, 2026-08-15 a Saturday.
    start_date: "2026-08-14",
    end_date: "2026-08-15",
    enabled_slots: ["BREAKFAST", "LUNCH", "DINNER"],
    default_servings: 2,
    shopping_list_id: null,
    meals_added_since_list: false,
    notes: null,
    entries: [],
    daily_nutrition_summary: [],
    created_by: "u1",
    created_at: "2026-08-14T08:00:00Z",
    updated_at: "2026-08-14T08:00:00Z",
  };
}

function renderCalendar() {
  const plan = mealPlan();
  const noop = vi.fn();
  return render(
    <MealPlanCalendar
      plan={plan}
      onAddEntry={noop}
      onRemoveEntry={noop}
      onCookEntry={noop}
      onMoveEntry={noop}
      t={tFor("recipes")}
    />,
  );
}

describe("MealPlanCalendar day/month labels", () => {
  it("renders Polish day and month names when the interface is Polish", async () => {
    await withLanguage("pl", () => {
      renderCalendar();
      // date-fns `pl` locale abbreviates weekdays with a trailing dot.
      expect(screen.getByText("pt.")).toBeInTheDocument();
      expect(screen.getByText("sob.")).toBeInTheDocument();
      expect(screen.getByText("14 sie")).toBeInTheDocument();
      expect(screen.queryByText("Fri")).not.toBeInTheDocument();
      expect(screen.queryByText(/Aug/)).not.toBeInTheDocument();
    });
  });

  it("keeps English day and month names in the English interface", async () => {
    await withLanguage("en", () => {
      renderCalendar();
      expect(screen.getByText("Fri")).toBeInTheDocument();
      expect(screen.getByText("Sat")).toBeInTheDocument();
      expect(screen.getByText("14 Aug")).toBeInTheDocument();
    });
  });
});

/**
 * Measured at 390px on a seven-day plan: the grid showed two and a half days,
 * 562 of its 928 pixels off-screen and no sign of it. This screen exists to
 * show a week — where the gaps are, what repeats — so on a phone the axis
 * turns: a day at a time, each meal on its own full-width row.
 */
describe("MealPlanCalendar on a phone", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it("gives every day of the plan its own block, with every meal named in it", async () => {
    await withLanguage("en", () => {
      const { container } = renderCalendar();

      // Both days of the plan, not the first two of seven columns.
      const days = container.querySelectorAll("section");
      expect(days).toHaveLength(2);
      // Each day names its three meals, so no cell depends on a row header
      // that has scrolled out of sight.
      for (const day of days) {
        for (const meal of ["Breakfast", "Lunch", "Dinner"]) {
          expect(
            [...day.querySelectorAll("p")].some((p) => p.textContent === meal),
          ).toBe(true);
        }
      }
    });
  });

  it("draws no horizontally scrolling grid at that width", async () => {
    await withLanguage("en", () => {
      const { container } = renderCalendar();

      expect(container.querySelector(".overflow-x-auto")).toBeNull();
      expect(container.querySelector(".min-w-\\[600px\\]")).toBeNull();
    });
  });
});

describe("MealPlanCalendar on a desktop", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  // jsdom has no layout, so the padding is pinned by its class. A filled
  // cell is `-m-0.5` to leave room for its drop ring; with no padding on the
  // grid the last column ran 2px past the track and the grid grew a scrollbar.
  it("pads the grid so the filled cells' negative margin stays inside it", () => {
    const { container } = renderCalendar();
    const grid = container.querySelector(".min-w-\\[600px\\]");
    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("p-0.5");
  });
});
