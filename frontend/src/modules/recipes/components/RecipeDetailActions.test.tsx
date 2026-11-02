import { describe, it, expect, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { RecipeDetailActions } from "./RecipeDetailActions";
import type { Recipe } from "../types/core";
import {
  moduleRegistry,
  slotComponent,
  type SlotDataMap,
} from "@/lib/moduleRegistry";

// The cook-for-stock sheet is the maker module's, drawn through the
// `recipe_cook_for_stock` slot. A stand-in contributor keeps this file about
// the recipe page: where the slot is mounted and who holds it open.
function CookForStockProbe({
  data,
}: {
  data: SlotDataMap["recipe_cook_for_stock"];
}) {
  if (!data.open) return null;
  return (
    <div role="dialog" aria-modal="true">
      Cook {data.recipe.name}
    </div>
  );
}
moduleRegistry.register({
  name: "maker",
  routes: [],
  slots: [
    {
      slot: "recipe_cook_for_stock",
      component: slotComponent(CookForStockProbe),
    },
  ],
});

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes", "maker"],
    isModuleEnabled: (name: string) => name === "maker",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/hooks/queries/useLocations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/queries/useLocations")>()),
  useLocationOffer: () => ({
    total: 0,
    first: [],
    emptyReason: "nothing-to-offer",
    isError: false,
    error: null,
    refetch: () => {},
  }),
  useLocationsById: () => ({ byId: new Map() }),
  useOfferedLocations: () => ({ data: [], isLoading: false }),
}));

const mealPlanMocks = vi.hoisted(() => ({
  useMealPlans: vi.fn().mockReturnValue({ data: [] }),
  useAddMealPlanEntry: vi.fn().mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}));

vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useMealPlans: mealPlanMocks.useMealPlans,
  useAddMealPlanEntry: mealPlanMocks.useAddMealPlanEntry,
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  useExportRecipe: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}));

const recipe: Recipe = {
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

const renderActions = (overrides: Partial<Recipe> = {}) => {
  const resolved = { ...recipe, ...overrides };
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <RecipeDetailActions
          recipe={resolved}
          justCompleted={false}
          hasInstructions={Boolean(resolved.instructions)}
          onToggleFavorite={vi.fn()}
          onDuplicate={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onStartPicking={vi.fn()}
          onStartCooking={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("RecipeDetailActions", () => {
  it("renders the secondary actions and the picking CTA", () => {
    renderActions();
    expect(screen.getByTitle("Edit")).toBeInTheDocument();
    expect(screen.getByText("Take from stock")).toBeInTheDocument();
  });

  it("hides the 'Cook a batch for stock' label below sm, keeping the icon", () => {
    renderActions();
    const label = screen.getByText("Cook a batch for stock");
    expect(label).toHaveClass("hidden", "sm:inline");
  });

  it("keeps stock/meal-plan actions out of the phone header via the ⋯ menu", () => {
    renderActions();
    // Inline labeled group renders only from sm up; on phones the two
    // actions live behind the ⋯ overflow button.
    const cookButton = screen.getByTestId("cook-for-stock-button");
    expect(cookButton).toHaveTextContent("Cook a batch for stock");
    expect(cookButton.closest(".hidden.sm\\:flex")).not.toBeNull();
  });

  it("keeps the ⋯ overflow available on every screen size", () => {
    renderActions();
    expect(
      screen.getByRole("button", { name: "More actions" }),
    ).not.toHaveClass("sm:hidden");
  });

  it("opens the ⋯ menu with the stock and meal-plan actions", () => {
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getAllByText("Add to meal plan").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Cook a batch for stock").length,
    ).toBeGreaterThan(0);
  });

  it("keeps the cook-action label readable inside the ⋯ menu", () => {
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    // Two matches once the menu opens: the header button (icon-only below
    // sm) and the menu item. The menu only exists on phones, so its label
    // must NOT carry the `hidden` class.
    const labels = screen.getAllByText("Cook a batch for stock");
    expect(labels.some((el) => !el.classList.contains("hidden"))).toBe(true);
  });

  it("adds the recipe to a meal plan from the header", () => {
    mealPlanMocks.useMealPlans.mockReturnValue({
      data: [
        {
          id: "p1",
          name: "Week 30",
          start_date: "2026-08-11",
          end_date: "2026-08-17",
          enabled_slots: ["LUNCH"],
          default_servings: 2,
          shopping_list_id: null,
          entry_count: 0,
        },
      ],
    });
    mealPlanMocks.useAddMealPlanEntry.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    renderActions();
    fireEvent.click(screen.getByTestId("add-to-meal-plan-button"));
    expect(screen.getByTestId("meal-plan-picker-plan")).toBeInTheDocument();
  });

  // The popper wrapper carries a `transform`, which makes it the containing
  // block of anything `position: fixed` inside it: a sheet opened from within
  // the menu was laid out against the 224 px menu, not the screen.
  describe.each(["Add to meal plan", "Cook a batch for stock"])(
    "the ⋯ menu action %s",
    (label) => {
      // The popover's own content is a `dialog` too; the sheet is the modal one.
      const findSheet = () =>
        waitFor(() => {
          const found = document.querySelector<HTMLElement>(
            "[role='dialog'][aria-modal='true']",
          );
          expect(found).not.toBeNull();
          return found as HTMLElement;
        });

      const openFromMenu = () => {
        renderActions();
        fireEvent.click(screen.getByRole("button", { name: "More actions" }));
        const menu = document.querySelector<HTMLElement>(
          "[data-radix-popper-content-wrapper]",
        );
        expect(menu).not.toBeNull();
        fireEvent.click(within(menu as HTMLElement).getByText(label));
      };

      it("opens its sheet outside the menu, with no transformed ancestor", async () => {
        openFromMenu();
        const sheet = await findSheet();
        expect(sheet.closest("[data-radix-popper-content-wrapper]")).toBeNull();
      });

      it("leaves the sheet open once the menu has closed", async () => {
        openFromMenu();
        const sheet = await findSheet();
        expect(
          document.querySelector("[data-radix-popper-content-wrapper]"),
        ).toBeNull();
        expect(sheet).toBeInTheDocument();
      });
    },
  );

  it("renders 'Cook step by step' as the primary action when instructions exist", () => {
    const onStartCooking = vi.fn();
    render(
      <MemoryRouter>
        <RecipeDetailActions
          recipe={{ ...recipe, instructions: "Mix everything." }}
          justCompleted={false}
          hasInstructions
          onToggleFavorite={vi.fn()}
          onDuplicate={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onStartPicking={vi.fn()}
          onStartCooking={onStartCooking}
        />
      </MemoryRouter>,
    );
    const cookButton = screen.getByRole("button", {
      name: "Cook step by step",
    });
    fireEvent.click(cookButton);
    expect(onStartCooking).toHaveBeenCalled();
  });

  it("omits the cooking action when the recipe has no instructions", () => {
    renderActions({ instructions: null });
    expect(
      screen.queryByRole("button", { name: "Cook step by step" }),
    ).not.toBeInTheDocument();
  });

  it("moves delete, duplicate and print behind the ⋯ menu", () => {
    renderActions();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Duplicate" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Print" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Duplicate" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();
  });
});
