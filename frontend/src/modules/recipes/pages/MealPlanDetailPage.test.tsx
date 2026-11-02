import { useState, type ReactNode } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { toast } from "sonner";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import type { MealPlan } from "@/modules/recipes/types/mealplans";
import MealPlanDetailPage from "./MealPlanDetailPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes", "shopping_lists"],
    isModuleEnabled: (name: string) => name === "shopping_lists",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const { updatePlanMock, pickingSessionMock, nutritionDays } = vi.hoisted(
  () => ({
    updatePlanMock: vi.fn(),
    pickingSessionMock: vi.fn(),
    nutritionDays: { current: [] as MealPlan["daily_nutrition_summary"] },
  }),
);

vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useMealPlan: () => ({ data: planFixture(), isLoading: false }),
  useAddMealPlanEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteMealPlanEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateMealPlan: () => ({ mutateAsync: updatePlanMock, isPending: false }),
  useUpdateMealPlanEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCopyPlanToWeek: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useGenerateMealPlanShoppingList: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  usePatchCookingHistory: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

// The picking checklist reaches the API through this hook; an open session
// is all the cook flow below needs to show its working screen.
vi.mock("@/modules/recipes/hooks/usePickingSession", () => ({
  usePickingSession: (...args: unknown[]) => {
    pickingSessionMock(...args);
    return {
      state: {
        phase: "active",
        session: {
          picking_session_id: "sess-1",
          recipe_name: "Pasta",
          servings: 2,
          items_to_pick: [],
        },
        items: [],
      },
      isLoading: false,
      error: null,
      refusals: {},
      startSession: vi.fn(),
      scan: vi.fn(),
      resolveDisambiguation: vi.fn(),
      undoPick: vi.fn(),
      dismissOpenedSuggestion: vi.fn(),
      completeSession: vi.fn(),
      cancelSession: vi.fn(),
      refreshSession: vi.fn(),
      reset: vi.fn(),
    };
  },
}));

function planFixture(): MealPlan {
  return {
    id: "mp1",
    name: "Test Week",
    start_date: "2026-08-14",
    end_date: "2026-08-15",
    enabled_slots: ["BREAKFAST", "LUNCH", "DINNER"],
    default_servings: 2,
    shopping_list_id: null,
    meals_added_since_list: false,
    notes: null,
    entries: [
      {
        id: "e1",
        date: "2026-08-14",
        slot: "DINNER",
        recipe_id: "r1",
        recipe_name: "Pasta",
        recipe_image_url: null,
        servings: 2,
        notes: null,
        order: 0,
        is_completed: false,
        picking_session_id: null,
      },
      {
        id: "e2",
        date: "2026-08-14",
        slot: "DINNER",
        recipe_id: "r2",
        recipe_name: "Soup",
        recipe_image_url: null,
        servings: 2,
        notes: null,
        order: 1,
        is_completed: false,
        picking_session_id: null,
      },
      {
        id: "e3",
        date: "2026-08-15",
        slot: "DINNER",
        recipe_id: "r1",
        recipe_name: "Pasta",
        recipe_image_url: null,
        servings: 2,
        notes: null,
        order: 0,
        is_completed: false,
        picking_session_id: null,
      },
      {
        id: "e4",
        date: "2026-08-14",
        slot: "LUNCH",
        recipe_id: "r2",
        recipe_name: "Soup",
        recipe_image_url: null,
        servings: 1,
        notes: null,
        order: 0,
        is_completed: false,
        picking_session_id: null,
      },
    ],
    daily_nutrition_summary: nutritionDays.current,
    created_by: "u1",
    created_at: "2026-08-14T08:00:00Z",
    updated_at: "2026-08-14T08:00:00Z",
  };
}

/** Mimics ModuleShell: renders header data set via useModulePageHeader. */
function ShellWrapper({ children }: { children: ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.title && <h1>{headerData.title}</h1>}
      {headerData.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/recipes/meal-planner/mp1"]}>
        <Routes>
          <Route
            path="/recipes/meal-planner/:id"
            element={
              <ShellWrapper>
                <MealPlanDetailPage />
              </ShellWrapper>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function slotConflictError(slot: string, count: number): Error {
  return Object.assign(new Error("Conflict"), {
    isAxiosError: true,
    response: {
      data: {
        detail: {
          code: "MEAL_PLAN_SLOT_CONFLICT",
          message: `Entries exist in disabled slots: ${slot}`,
          conflicts: [{ slot, count }],
        },
      },
    },
  });
}

describe("MealPlanDetailPage slot conflict dialog", () => {
  beforeEach(() => {
    updatePlanMock.mockReset();
    signInWith(["recipes:read", "recipes:write", "recipes:consume"]);
  });

  afterEach(() => signOut());

  it("shows a dialog naming the conflicting slot and entry count, and re-sends the PATCH with the removal flag on confirm", async () => {
    updatePlanMock
      .mockRejectedValueOnce(slotConflictError("DINNER", 3))
      .mockResolvedValueOnce(planFixture());

    renderPage();

    // Open the settings panel (gear button in the page header).
    fireEvent.click(screen.getByRole("button", { name: "Plan settings" }));

    // Disable the active Dinner slot — the API answers 409.
    fireEvent.click(screen.getByRole("button", { name: "Dinner" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("Dinner")).toBeInTheDocument();
    expect(within(dialog).getByText("3 planned meals")).toBeInTheDocument();

    // Confirm — the retry PATCH must carry the removal flag.
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: /disable and remove entries/i,
      }),
    );

    // Success closes the dialog; waiting for that gives the post-mutation
    // state updates somewhere inside act to land instead of after the test.
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );

    expect(updatePlanMock).toHaveBeenCalledTimes(2);
    expect(updatePlanMock.mock.calls[1][0]).toMatchObject({
      id: "mp1",
      data: {
        enabled_slots: ["BREAKFAST", "LUNCH"],
        remove_conflicting_entries: true,
      },
    });
  });

  it("falls back to the generic update error for other failures", async () => {
    updatePlanMock.mockRejectedValueOnce(
      Object.assign(new Error("Boom"), {
        isAxiosError: true,
        response: {
          data: { detail: { code: "SOMETHING_ELSE", message: "x" } },
        },
      }),
    );

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Plan settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Dinner" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Could not update plan"),
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});

describe("MealPlanDetailPage cook flow", () => {
  beforeEach(() => {
    pickingSessionMock.mockClear();
    signInWith(["recipes:read", "recipes:write", "recipes:consume"]);
    // A past day offers no cooking; stand on the plan's first day.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-08-14T08:00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
    signOut();
  });

  it("starts the cook from the card it was pressed on, not a sibling planned for the same recipe", async () => {
    renderPage();
    // Pasta is planned on the 14th (e1) and on the 15th (e3): the second
    // Cook Now button is the card of the 15th.
    const cookButtons = screen.getAllByRole("button", { name: /^Cook Now/ });
    const pastaCards = cookButtons.filter(
      (button) =>
        within(button.parentElement!.parentElement!).queryByText("Pasta") !==
        null,
    );
    expect(pastaCards).toHaveLength(2);

    fireEvent.click(pastaCards[1]);

    await screen.findAllByRole("dialog");
    expect(pickingSessionMock).toHaveBeenCalledWith("r1", "e3");
    expect(pickingSessionMock).not.toHaveBeenCalledWith("r1", "e1");
  });

  // The picking screens bring their own sheets. Wrapped in a sheet of the
  // page's, the wrapper's backdrop stood above the checklist: every tap on
  // an ingredient or on Finish picking landed on it and closed the flow.
  it("opens the picking checklist as the only dialog on the page", async () => {
    renderPage();

    fireEvent.click(screen.getAllByRole("button", { name: /^Cook Now/ })[0]);

    const dialogs = await screen.findAllByRole("dialog");
    expect(dialogs).toHaveLength(1);
    expect(
      within(dialogs[0]).getAllByRole("button", { name: /finish picking/i })
        .length,
    ).toBeGreaterThan(0);
  });
});

describe("MealPlanDetailPage daily nutrition", () => {
  beforeEach(() => {
    signInWith(["recipes:read"]);
  });

  afterEach(() => {
    nutritionDays.current = [];
    signOut();
  });

  it("flags a day at 90% coverage: a whole dish can hide in the other tenth", () => {
    nutritionDays.current = [
      {
        date: "2026-08-16",
        calories_kcal: 810,
        protein_g: null,
        fat_g: 90,
        carbs_g: null,
        coverage: 0.9,
        generic_values: false,
      },
    ];
    renderPage();

    expect(
      screen.getByText("Nutrition data available for 90% of ingredients only"),
    ).toBeInTheDocument();
  });

  it("says how much of a day was measured, and prints a dash for a nutrient nobody measured", () => {
    nutritionDays.current = [
      {
        date: "2026-08-14",
        calories_kcal: 244,
        protein_g: null,
        fat_g: 27.6,
        carbs_g: null,
        coverage: 0.33,
        generic_values: false,
      },
      {
        date: "2026-08-15",
        calories_kcal: 500,
        protein_g: 20,
        fat_g: 10,
        carbs_g: 60,
        coverage: 1,
        generic_values: false,
      },
    ];
    renderPage();

    const note = screen.getByText(
      "Nutrition data available for 33% of ingredients only",
    );
    expect(screen.getAllByText(/ingredients only/)).toHaveLength(1);
    // The note belongs to the partly measured day, not to the complete one.
    const first = within(screen.getByRole("table"))
      .getByText(/14 Aug/)
      .closest("tbody")!;
    expect(first).toContainElement(note);
    expect(within(first).getAllByText("–")).toHaveLength(2);
    expect(screen.queryByText("0 g")).not.toBeInTheDocument();
  });
});
