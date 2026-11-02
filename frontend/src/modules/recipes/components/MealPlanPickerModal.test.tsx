import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { toast } from "sonner";
import {
  AddToMealPlanButton,
  MealPlanPickerModal,
} from "./MealPlanPickerModal";
import type { Recipe } from "../types/core";
import type { MealPlanListItem } from "../types/mealplans";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mocks = vi.hoisted(() => ({
  useMealPlans: vi.fn(),
  useAddMealPlanEntry: vi.fn(),
}));

vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useMealPlans: mocks.useMealPlans,
  useAddMealPlanEntry: mocks.useAddMealPlanEntry,
}));

const plans: MealPlanListItem[] = [
  {
    updated_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    id: "p1",
    name: "Week 30",
    start_date: "2026-08-11",
    end_date: "2026-08-17",
    enabled_slots: ["BREAKFAST", "LUNCH", "DINNER", "SNACK"],
    default_servings: 2,
    shopping_list_id: null,
    entry_count: 0,
  },
];

const recipe: Recipe = {
  id: "r1",
  organization_id: "o1",
  created_by: "u1",
  name: "Pancakes",
  description: null,
  instructions: null,
  servings: 4,
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

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">{location.pathname + location.search}</div>
  );
}

function renderInRouter(node: ReactNode) {
  return render(
    <MemoryRouter initialEntries={["/recipes/r1"]}>
      <Routes>
        <Route path="/recipes/r1" element={node} />
        <Route path="/recipes/meal-planner" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const renderModal = (onClose = vi.fn()) =>
  renderInRouter(
    <MealPlanPickerModal open onClose={onClose} recipe={recipe} />,
  );

describe("MealPlanPickerModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useMealPlans.mockReturnValue({ data: plans });
    mocks.useAddMealPlanEntry.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
  });

  it("shows a hint when no plans exist yet", () => {
    mocks.useMealPlans.mockReturnValue({ data: [] });
    renderModal();
    expect(screen.getByText(/Create a meal plan first/)).toBeInTheDocument();
  });

  it("gives the empty state an exit and a way to create a plan", () => {
    mocks.useMealPlans.mockReturnValue({ data: [] });
    const onClose = vi.fn();
    renderModal(onClose);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "New Plan" }));
    // The planner opens its create form and keeps the recipe to place.
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/recipes/meal-planner?new=1&recipe=r1",
    );
  });

  it("adds the recipe to the chosen plan, day and slot", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    mocks.useAddMealPlanEntry.mockReturnValue({
      mutateAsync,
      isPending: false,
    });
    const onClose = vi.fn();
    renderModal(onClose);

    fireEvent.change(screen.getByTestId("meal-plan-picker-plan"), {
      target: { value: "p1" },
    });
    fireEvent.change(screen.getByTestId("meal-plan-picker-day"), {
      target: { value: "2026-08-12" },
    });
    fireEvent.change(screen.getByTestId("meal-plan-picker-slot"), {
      target: { value: "DINNER" },
    });
    fireEvent.click(screen.getByTestId("meal-plan-picker-submit"));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        planId: "p1",
        data: { date: "2026-08-12", slot: "DINNER", recipe_id: "r1" },
      });
    });
    expect(toast.success).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("disables submit until plan, day and slot are chosen", () => {
    renderModal();
    const submit = screen.getByTestId("meal-plan-picker-submit");
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("meal-plan-picker-plan"), {
      target: { value: "p1" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("meal-plan-picker-day"), {
      target: { value: "2026-08-12" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("meal-plan-picker-slot"), {
      target: { value: "LUNCH" },
    });
    expect(submit).toBeEnabled();
  });

  it("shows only the plan's enabled slots", () => {
    mocks.useMealPlans.mockReturnValue({
      data: [
        {
          ...plans[0],
          enabled_slots: ["LUNCH", "SNACK"],
        },
      ],
    });
    renderModal();
    fireEvent.change(screen.getByTestId("meal-plan-picker-plan"), {
      target: { value: "p1" },
    });
    const slot = screen.getByTestId(
      "meal-plan-picker-slot",
    ) as HTMLSelectElement;
    const options = Array.from(slot.options).map((o) => o.textContent);
    expect(options).toContain("Lunch");
    expect(options).toContain("Snack");
    expect(options).not.toContain("Breakfast");
    expect(options).not.toContain("Dinner");
  });
});

describe("AddToMealPlanButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useMealPlans.mockReturnValue({ data: plans });
    mocks.useAddMealPlanEntry.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
  });

  it("opens the picker modal on click", () => {
    renderInRouter(<AddToMealPlanButton recipe={recipe} />);
    expect(screen.queryByText("Add to meal plan")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("add-to-meal-plan-button"));
    expect(screen.getByTestId("meal-plan-picker-plan")).toBeInTheDocument();
  });
});

describe("MealPlanPickerModal — the dates the plan carries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useMealPlans.mockReturnValue({ data: plans });
    mocks.useAddMealPlanEntry.mockReturnValue({ mutateAsync: vi.fn() });
  });

  it("names each plan by its range as well as its name", () => {
    // A plan name is free text. "Week 2" and "Week 3" tell them apart only
    // for whoever wrote them, and the range came down with the list.
    mocks.useMealPlans.mockReturnValue({
      data: [plans[0], { ...plans[0], id: "p2", name: "Week 31" }],
    });
    renderModal();

    const plan = screen.getByTestId<HTMLSelectElement>("meal-plan-picker-plan");
    expect(Array.from(plan.options).map((o) => o.textContent)).toContain(
      "Week 30 · 11–17 Aug 2026",
    );
  });

  it("keeps the order the server sent, which is by start date", () => {
    mocks.useMealPlans.mockReturnValue({
      data: [
        { ...plans[0], id: "p3", name: "Aaa later" },
        { ...plans[0], id: "p1", name: "Zzz earlier" },
      ],
    });
    renderModal();

    const plan = screen.getByTestId<HTMLSelectElement>("meal-plan-picker-plan");
    expect(
      Array.from(plan.options)
        .map((o) => o.value)
        .filter(Boolean),
    ).toEqual(["p3", "p1"]);
  });

  it("says which weekday each day is", () => {
    renderModal();

    const day = screen.getByTestId<HTMLSelectElement>("meal-plan-picker-day");
    const labels = Array.from(day.options).map((o) => o.textContent);
    expect(labels).toContain("Tue, 11 Aug");
    expect(labels).not.toContain("2026-08-11");
  });
});

describe("MealPlanPickerModal — it answers what it can before asking", () => {
  beforeEach(() => {
    mocks.useMealPlans.mockReturnValue({ data: plans });
    mocks.useAddMealPlanEntry.mockReturnValue({ mutateAsync: vi.fn() });
  });

  it("picks the only plan there is, and shows the day and the meal", () => {
    // The modal opened on one question — which plan — and revealed the day
    // and the meal only once it was answered. With a single plan that is a
    // list of one standing between the reader and the actual question.
    renderInRouter(
      <MealPlanPickerModal open onClose={vi.fn()} recipe={recipe} />,
    );

    expect(
      screen.getByTestId<HTMLSelectElement>("meal-plan-picker-plan").value,
    ).toBe("p1");
    expect(screen.getByTestId("meal-plan-picker-day")).toBeInTheDocument();
    expect(screen.getByTestId("meal-plan-picker-slot")).toBeInTheDocument();
  });

  it("starts on a day the plan actually covers", () => {
    renderInRouter(
      <MealPlanPickerModal open onClose={vi.fn()} recipe={recipe} />,
    );

    const day = screen.getByTestId<HTMLSelectElement>("meal-plan-picker-day");
    expect(day.value).toBe("2026-08-11");
  });

  it("picks the meal when the plan runs only one", () => {
    mocks.useMealPlans.mockReturnValue({
      data: [{ ...plans[0], enabled_slots: ["DINNER"] }],
    });

    renderInRouter(
      <MealPlanPickerModal open onClose={vi.fn()} recipe={recipe} />,
    );

    expect(
      screen.getByTestId<HTMLSelectElement>("meal-plan-picker-slot").value,
    ).toBe("DINNER");
  });

  it("marks the reader's own today, not the UTC one", () => {
    // The day list is built from the plan's calendar days; the day marked as
    // "today" has to be read the same way. Through `toISOString()`, a plan
    // opened west of Greenwich after 17:00 highlighted tomorrow's row.
    const original = process.env.TZ;
    process.env.TZ = "America/Los_Angeles";
    vi.useFakeTimers();
    // 20:00 on 11 August local is already 03:00 on the 12th in UTC.
    vi.setSystemTime(new Date(2026, 7, 11, 20, 0));
    try {
      renderInRouter(
        <MealPlanPickerModal open onClose={vi.fn()} recipe={recipe} />,
      );

      expect(
        screen.getByTestId<HTMLSelectElement>("meal-plan-picker-day").value,
      ).toBe("2026-08-11");
    } finally {
      vi.useRealTimers();
      process.env.TZ = original;
    }
  });

  it("walks the plan's own days, whatever the reader's zone", () => {
    // Documents the walk rather than a fix: the cursor is built from the
    // plan's `yyyy-MM-dd` and stepped in UTC, so it emits those exact days
    // in any zone. A rewrite into local dates has to keep that property.
    const original = process.env.TZ;
    process.env.TZ = "America/Los_Angeles";
    try {
      renderModal();

      const day = screen.getByTestId<HTMLSelectElement>("meal-plan-picker-day");
      expect(
        Array.from(day.options)
          .map((o) => o.value)
          .filter(Boolean),
      ).toEqual([
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
        "2026-08-15",
        "2026-08-16",
        "2026-08-17",
      ]);
    } finally {
      process.env.TZ = original;
    }
  });

  it("still asks which plan when there is more than one", () => {
    mocks.useMealPlans.mockReturnValue({
      data: [plans[0], { ...plans[0], id: "p2", name: "Week 31" }],
    });

    renderInRouter(
      <MealPlanPickerModal open onClose={vi.fn()} recipe={recipe} />,
    );

    expect(
      screen.getByTestId<HTMLSelectElement>("meal-plan-picker-plan").value,
    ).toBe("");
    expect(
      screen.queryByTestId("meal-plan-picker-day"),
    ).not.toBeInTheDocument();
  });
});
