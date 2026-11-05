import { useState, type ReactNode } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import type { MealPlanListItem } from "@/modules/recipes/types/mealplans";
import { signInWith, signOut } from "@/test/auth";
import MealPlannerPage from "./MealPlannerPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const planItem: MealPlanListItem = {
  updated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  id: "mp1",
  name: "Week 33",
  start_date: "2026-08-14",
  end_date: "2026-08-20",
  enabled_slots: ["BREAKFAST", "LUNCH", "DINNER"],
  default_servings: 2,
  shopping_list_id: null,
  entry_count: 3,
};

const modulesMock = vi.hoisted(() => ({ shoppingListsEnabled: true }));
const deleteMock = vi.hoisted(() => ({
  mutateAsync: vi.fn().mockResolvedValue(undefined),
}));
const plansMock = vi.hoisted(() => ({ data: [] as MealPlanListItem[] }));
const generateMock = vi.hoisted(() => ({ mutateAsync: vi.fn() }));
const createMock = vi.hoisted(() => ({ mutateAsync: vi.fn() }));
const addEntryMock = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  isPending: false,
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: modulesMock.shoppingListsEnabled ? ["shopping_lists"] : [],
    isModuleEnabled: (name: string) =>
      name === "shopping_lists" && modulesMock.shoppingListsEnabled,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useMealPlans: () => ({ data: plansMock.data, isLoading: false }),
  useCreateMealPlan: () => ({
    mutateAsync: createMock.mutateAsync,
    isPending: false,
  }),
  useAddMealPlanEntry: () => ({
    mutateAsync: addEntryMock.mutateAsync,
    isPending: addEntryMock.isPending,
  }),
  useDeleteMealPlan: () => ({
    mutateAsync: deleteMock.mutateAsync,
    isPending: false,
  }),
  useGenerateMealPlanShoppingList: () => ({
    mutateAsync: generateMock.mutateAsync,
    isPending: false,
  }),
}));

function ShellWrapper({ children }: { children: ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

function renderPage(plans: MealPlanListItem[] = [planItem], url = "/") {
  plansMock.data = plans;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <ShellWrapper>
          <Routes>
            <Route path="/" element={<MealPlannerPage />} />
            <Route path="/recipes/meal-planner" element={<MealPlannerPage />} />
            <Route
              path="/recipes/meal-planner/:id"
              element={<LocationProbe />}
            />
          </Routes>
        </ShellWrapper>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MealPlannerPage grid", () => {
  it("uses an auto-fit grid so a single plan fills the available width", () => {
    const { container } = renderPage();
    expect(screen.getByText("Week 33")).toBeInTheDocument();
    const grid = container.querySelector('[class*="auto-fit"]');
    expect(grid).not.toBeNull();
  });

  it("names the other open list when the generated one repeats its goods", async () => {
    generateMock.mutateAsync.mockResolvedValue({
      shopping_list_id: "sl2",
      on_other_lists: [{ name: "Flour", list_id: "sl1", list_name: "Week 30" }],
    });
    signInWith(["recipes:write"]);
    try {
      renderPage();
      fireEvent.click(
        screen.getByRole("button", { name: /generate shopping list/i }),
      );
      await waitFor(() => expect(toast.warning).toHaveBeenCalled());
      const message = vi.mocked(toast.warning).mock.calls[0][0] as string;
      expect(message).toContain("Flour");
      expect(message).toContain("Week 30");
    } finally {
      signOut();
    }
  });

  it("hides the shopping-list action when the shopping_lists module is disabled", () => {
    modulesMock.shoppingListsEnabled = false;
    renderPage();
    expect(screen.getByText("Week 33")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /generate shopping list/i }),
    ).not.toBeInTheDocument();
    modulesMock.shoppingListsEnabled = true;
  });
});

/**
 * One click on the bin used to hard-delete the plan and every meal on it,
 * with no way back. The delete now waits for an answer that says how many
 * meals go with it.
 */
describe("MealPlannerPage — deleting a plan asks first", () => {
  beforeEach(() => {
    deleteMock.mutateAsync.mockClear();
    signInWith(["recipes:write"]);
  });
  afterEach(() => signOut());

  it("sends nothing on the click and names the meals that would go", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Delete plan" }));

    expect(deleteMock.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "The plan and its 3 planned meals will be deleted for good.",
    );
  });

  it("keeps the plan when the question is cancelled", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Delete plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(deleteMock.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("deletes that plan once the question is confirmed", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Delete plan" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Delete plan" }),
    );

    await waitFor(() =>
      expect(deleteMock.mutateAsync).toHaveBeenCalledWith("mp1"),
    );
  });
});

/**
 * A new plan opens on the reader's own week and those dates are saved.
 * Built through `toISOString()`, both ends answered in UTC: east of
 * Greenwich just after midnight the plan started yesterday, and the
 * six-day window slid with it.
 */
describe("MealPlannerPage — the week a new plan covers", () => {
  it("starts on the reader's today, six days before the end", () => {
    // The create action is write-gated, so the reader has to be one who may
    // write before the form can be opened at all.
    signInWith(["recipes:write"]);
    const original = process.env.TZ;
    process.env.TZ = "Europe/Warsaw";
    vi.useFakeTimers();
    // 00:30 on 11 September 2026 local is still 22:30 on the 10th in UTC.
    vi.setSystemTime(new Date(2026, 8, 11, 0, 30));
    try {
      renderPage();
      fireEvent.click(screen.getByRole("button", { name: "New Plan" }));

      expect(screen.getByLabelText("Start date")).toHaveTextContent(
        "Sep 11, 2026",
      );
      expect(screen.getByLabelText("End date")).toHaveTextContent(
        "Sep 17, 2026",
      );
    } finally {
      vi.useRealTimers();
      process.env.TZ = original;
      signOut();
    }
  });
});

describe("MealPlannerPage — the empty planner explains itself", () => {
  it("keeps the explanation out of the heading", () => {
    renderPage([]);

    const empty = screen.getByTestId("empty-state");
    expect(
      within(empty).getByRole("heading", {
        level: 2,
        name: "No meal plans yet",
      }),
    ).toBeInTheDocument();
    expect(
      within(empty).getByText(
        "Plan a range of days, fill the slots with recipes — the plan can feed a shopping list.",
      ),
    ).toBeInTheDocument();
  });
});

/**
 * A recipe with no plan to go into sends the reader here with "?new=1": the
 * create form is open on arrival, and the plan that comes out of it holds the
 * recipe instead of leaving the reader to find it again.
 */
describe("MealPlannerPage — arriving from a recipe with no plan", () => {
  beforeEach(() => {
    createMock.mutateAsync.mockReset();
    addEntryMock.mutateAsync.mockReset().mockResolvedValue({});
    addEntryMock.isPending = false;
    signInWith(["recipes:write"]);
  });
  afterEach(() => signOut());

  it("opens the create form without a click", () => {
    renderPage([], "/recipes/meal-planner?new=1&recipe=r1");
    expect(
      screen.getByRole("dialog", { name: "New Plan" }),
    ).toBeInTheDocument();
  });

  it("puts the recipe on the new plan and opens the plan", async () => {
    createMock.mutateAsync.mockResolvedValue({ id: "mp9" });
    renderPage([], "/recipes/meal-planner?new=1&recipe=r1");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(addEntryMock.mutateAsync).toHaveBeenCalledWith({
        planId: "mp9",
        data: expect.objectContaining({ slot: "BREAKFAST", recipe_id: "r1" }),
      }),
    );
    expect(await screen.findByTestId("location")).toHaveTextContent(
      "/recipes/meal-planner/mp9",
    );
  });

  it("keeps the form open and retries only the placement when it fails", async () => {
    createMock.mutateAsync.mockResolvedValue({ id: "mp9" });
    addEntryMock.mutateAsync
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue({});
    renderPage([], "/recipes/meal-planner?new=1&recipe=r1");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(addEntryMock.mutateAsync).toHaveBeenCalled());
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "New Plan" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByTestId("location")).toHaveTextContent(
      "/recipes/meal-planner/mp9",
    );
    expect(createMock.mutateAsync).toHaveBeenCalledTimes(1);
    expect(addEntryMock.mutateAsync).toHaveBeenCalledTimes(2);
    expect(addEntryMock.mutateAsync).toHaveBeenLastCalledWith({
      planId: "mp9",
      data: expect.objectContaining({ recipe_id: "r1" }),
    });
  });

  it("cannot be submitted again while the recipe is being placed", () => {
    addEntryMock.isPending = true;
    renderPage([], "/recipes/meal-planner?new=1&recipe=r1");
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  });

  it("leaves a plan made from the plain button where it was", async () => {
    createMock.mutateAsync.mockResolvedValue({ id: "mp9" });
    renderPage([]);
    fireEvent.click(screen.getAllByRole("button", { name: "New Plan" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createMock.mutateAsync).toHaveBeenCalled());
    expect(addEntryMock.mutateAsync).not.toHaveBeenCalled();
  });
});
