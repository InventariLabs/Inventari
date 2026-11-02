import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { signInWith, signOut } from "@/test/auth";
import { MealPlanCell } from "./MealPlanCell";
import en from "@/modules/recipes/i18n/en.json";

// "Cook Now" is `recipes:consume` on the API; the card asks before offering
// it. These tests exercise the card as a cook unless a test says otherwise.
beforeEach(() => signInWith(["recipes:read", "recipes:consume"]));
afterEach(signOut);

const t = (key: string, opts?: Record<string, unknown>) => {
  const path = key.replace("recipes:", "").split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = en;
  for (const part of path) value = value?.[part];
  if (typeof value !== "string") return key;
  return value.replace(/\{\{(\w+)\}\}/g, (m: string, name: string) =>
    String(opts?.[name] ?? m),
  );
};

const entry = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: "e1",
  plan_id: "p1",
  recipe_id: "r1",
  recipe_name: "Pancakes",
  date: "2026-07-01",
  slot: "LUNCH" as const,
  servings: 2,
  order: 0,
  is_completed: false,
  picking_session_id: null,
  recipe_image_url: null,
  notes: null,
  ...overrides,
});

const baseProps = {
  date: "2026-07-01",
  slot: "LUNCH" as const,
  slotLabel: "Lunch",
  onAdd: vi.fn(),
  onRemove: vi.fn(),
  onCook: vi.fn(),
  t,
};

describe("MealPlanCell — past days", () => {
  it("marks past un-cooked meals as not cooked", () => {
    render(<MealPlanCell {...baseProps} isPast entries={[entry()]} />);
    expect(screen.getByText("Not cooked")).toBeInTheDocument();
    expect(screen.getByText("Pancakes")).toBeInTheDocument();
  });

  it("does not mark past cooked meals", () => {
    render(
      <MealPlanCell
        {...baseProps}
        isPast
        entries={[entry({ is_completed: true })]}
      />,
    );
    expect(screen.queryByText("Not cooked")).not.toBeInTheDocument();
  });

  it("hides cook/remove actions for past days", () => {
    render(<MealPlanCell {...baseProps} isPast entries={[entry()]} />);
    expect(screen.queryByText("Cook now")).not.toBeInTheDocument();
  });

  it("hides Cook Now from a planner who may not consume, keeping remove", () => {
    // Cooking checks `recipes:consume`; removing and moving the entry check
    // `recipes:write`. Signed out, the card holds no consume grant — while
    // `canWrite` is the writer's.
    signOut();
    render(<MealPlanCell {...baseProps} isPast={false} entries={[entry()]} />);

    expect(screen.queryByText("Cook Now")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Remove Pancakes from plan" }),
    ).toBeInTheDocument();
  });
});

describe("MealPlanCell — add-to-slot button", () => {
  it("names the icon-only add button by both aria-label and title", () => {
    render(<MealPlanCell {...baseProps} isPast={false} entries={[entry()]} />);
    const add = screen.getByRole("button", { name: /Add a meal: Lunch/ });
    expect(add.getAttribute("title")).toMatch(/Add a meal: Lunch/);
  });
});

describe("MealPlanCell — empty cell keyboard access", () => {
  it("adds a meal on Enter and on Space", () => {
    const onAdd = vi.fn();
    render(
      <MealPlanCell {...baseProps} isPast={false} entries={[]} onAdd={onAdd} />,
    );
    const cell = screen.getByRole("button", {
      name: /Add a meal: Lunch/,
    });
    fireEvent.keyDown(cell, { key: "Enter" });
    expect(onAdd).toHaveBeenCalledWith("2026-07-01", "LUNCH");

    onAdd.mockClear();
    fireEvent.keyDown(cell, { key: " " });
    expect(onAdd).toHaveBeenCalledWith("2026-07-01", "LUNCH");
  });
});

// On a phone, "Remove meal from plan" and "Drag to move" measured
// 16x16, side by side with a 4px gap: one thumb aimed at the handle pressed
// the destructive action beside it. Every control on that list is now 44px
// below `md` (Button `h-11 md:h-10`), and remove is out of the row entirely —
// it sits in the card's corner, a whole card away from the handle.
describe("MealPlanCell — touch targets", () => {
  it("gives remove and the drag handle a 44px target each, apart", () => {
    render(<MealPlanCell {...baseProps} isPast={false} entries={[entry()]} />);

    const remove = screen.getByRole("button", {
      name: "Remove Pancakes from plan",
    });
    const handle = screen.getByRole("button", {
      name: "Drag to move: Pancakes",
    });
    const cook = screen.getByRole("button", { name: "Cook Now: Pancakes" });
    const add = screen.getByRole("button", { name: /Add a meal: Lunch/ });

    for (const control of [remove, handle, cook, add]) {
      expect(String(control.className)).toContain("h-11");
    }

    // Corner, not row: the handle is the only control left down there.
    expect(String(remove.className)).toContain("absolute");
    expect(remove.parentElement).not.toBe(handle.parentElement);
    expect(String(handle.className)).toContain("ml-auto");
  });
});

// A week of cards read as "Cook Now", "Cook Now", "Cook Now" to a screen
// reader: the actions now carry the meal they act on.
describe("MealPlanCell — row actions name their meal", () => {
  it("tells two meals' actions apart", () => {
    render(
      <MealPlanCell
        {...baseProps}
        isPast={false}
        entries={[
          entry(),
          entry({ id: "e2", recipe_name: "Fried rice", order: 1 }),
        ]}
      />,
    );

    for (const recipe of ["Pancakes", "Fried rice"]) {
      expect(
        screen.getByRole("button", { name: `Cook Now: ${recipe}` }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: `Remove ${recipe} from plan` }),
      ).toBeInTheDocument();
    }
  });
});
