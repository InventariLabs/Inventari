import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MealPlanCard } from "./MealPlanCard";
import en from "@/modules/recipes/i18n/en.json";
import type { MealPlanListItem } from "@/modules/recipes/types/mealplans";

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

const basePlan: MealPlanListItem = {
  updated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  id: "p1",
  name: "Week plan",
  start_date: "2026-08-11",
  end_date: "2026-08-17",
  enabled_slots: [],
  default_servings: 2,
  shopping_list_id: null,
  entry_count: 3,
};

const renderCard = (plan: MealPlanListItem) =>
  render(
    <MemoryRouter>
      <MealPlanCard
        plan={plan}
        onDelete={vi.fn()}
        onGenerateShoppingList={vi.fn()}
        t={t}
      />
    </MemoryRouter>,
  );

describe("MealPlanCard shopping-list CTA", () => {
  it("styles the link as a real button instead of a token that is white in both themes", () => {
    renderCard({ ...basePlan, shopping_list_id: "sl-1" });
    const cta = screen.getByRole("link", {
      name: new RegExp(en.meal_planner.view_shopping_list, "i"),
    });

    // `--accent-foreground` is 255 255 255 in `:root` and never remapped, so on
    // the card's transparent background the label measured 1.00:1 in light mode
    // — white text on a white card.
    expect(cta.className).not.toContain("text-accent-foreground");
    expect(cta.className).not.toContain("bg-transparent");
    expect(cta.className).toContain("bg-surface-raised");
  });
});

describe("MealPlanCard — generated shopping list badge", () => {
  it("shows the badge with a readable success variant when a list exists", () => {
    renderCard({ ...basePlan, shopping_list_id: "sl1" });
    const badge = screen.getByText("Shopping list ready");
    // Badge variant="success" — explicit colors in both themes; the old
    // `text-accent-foreground` on the transparent outline variant was
    // invisible in light mode.: success now uses the semantic
    // success-* ramp, not the profile-repainted accent. The dark half moved
    // from `dark:text-success-400` (emerald-700 on a dark surface, 1.9:1) to
    // the theme-aware `text-on-success` foreground token.
    expect(badge).toHaveClass("bg-success-100");
    expect(badge).toHaveClass("text-on-success");
    expect(badge).not.toHaveClass("border-accent");
    expect(badge).not.toHaveClass("text-accent-foreground");
  });

  it("hides the badge when no shopping list was generated", () => {
    renderCard(basePlan);
    expect(screen.queryByText("Shopping list ready")).not.toBeInTheDocument();
  });

  it("makes the whole card header a link to the plan", () => {
    renderCard(basePlan);
    const link = screen.getByRole("link", { name: /week plan/i });
    expect(link).toHaveAttribute("href", "/recipes/meal-planner/p1");
    // The chevron no longer needs its own link
    expect(
      screen.getAllByRole("link").every((l) => l.getAttribute("href") !== null),
    ).toBe(true);
  });

  it("hides the shopping-list actions when the shopping_lists module is disabled", () => {
    render(
      <MemoryRouter>
        <MealPlanCard
          plan={basePlan}
          onDelete={vi.fn()}
          onGenerateShoppingList={vi.fn()}
          shoppingListsEnabled={false}
          t={t}
        />
      </MemoryRouter>,
    );
    expect(
      screen.queryByRole("button", { name: /generate shopping list/i }),
    ).not.toBeInTheDocument();
  });
});
