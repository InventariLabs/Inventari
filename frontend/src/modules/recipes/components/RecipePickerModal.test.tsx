import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { RecipePickerModal } from "./RecipePickerModal";

const mocks = vi.hoisted(() => ({
  useMealPlanSuggestions: vi.fn(),
  useRecipes: vi.fn(),
}));

vi.mock("@/modules/recipes/hooks/useMealPlanSuggestions", () => ({
  useMealPlanSuggestions: mocks.useMealPlanSuggestions,
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  useRecipes: mocks.useRecipes,
}));

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">
      {location.pathname}
      {location.search}
    </div>
  );
}

function renderModal(onClose = vi.fn(), canWrite = true) {
  return render(
    <MemoryRouter initialEntries={["/recipes/meal-planner/mp1"]}>
      <Routes>
        <Route
          path="/recipes/meal-planner/:id"
          element={
            <RecipePickerModal
              isOpen
              date="2026-09-01"
              slot="DINNER"
              planId="mp1"
              canWrite={canWrite}
              onSelect={vi.fn()}
              onClose={onClose}
            />
          }
        />
        <Route path="/recipes" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RecipePickerModal — an empty picker is not a dead end", () => {
  it("offers a way to create a recipe and a way out when there are none", () => {
    mocks.useMealPlanSuggestions.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    mocks.useRecipes.mockReturnValue({
      data: { items: [], total: 0 },
      isError: false,
      refetch: vi.fn(),
    });
    const onClose = vi.fn();
    renderModal(onClose);

    // The modal lands on the "all" tab when nothing is suggested.
    expect(screen.getByText("No recipes yet")).toBeInTheDocument();
    expect(
      screen.getByText("Create your first recipe to get started"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "New recipe" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/recipes?new=1");
  });

  it("keeps the exit visible when a search finds nothing", () => {
    mocks.useMealPlanSuggestions.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    mocks.useRecipes.mockReturnValue({
      data: { items: [], total: 0 },
      isError: false,
      refetch: vi.fn(),
    });
    const onClose = vi.fn();
    renderModal(onClose);

    fireEvent.change(screen.getByLabelText(/Search recipes/), {
      target: { value: "zzz" },
    });

    expect(
      screen.getByText("No recipes match your search"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New recipe" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("does not offer creating a recipe to a reader who cannot write", () => {
    mocks.useMealPlanSuggestions.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    mocks.useRecipes.mockReturnValue({
      data: { items: [], total: 0 },
      isError: false,
      refetch: vi.fn(),
    });
    renderModal(vi.fn(), false);

    expect(
      screen.queryByRole("button", { name: "New recipe" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });
});

describe("RecipePickerModal — one height for both lists", () => {
  function twoLists() {
    mocks.useMealPlanSuggestions.mockReturnValue({
      data: [
        {
          recipe_id: "r1",
          recipe_name: "Plain rice",
          image_url: null,
          match_percent: 100,
          missing_ingredients: [],
        },
      ],
      isLoading: false,
      isError: false,
    });
    mocks.useRecipes.mockReturnValue({
      data: {
        items: [
          { id: "r1", name: "Plain rice", image_url: null },
          { id: "r2", name: "Soup", image_url: null },
          { id: "r3", name: "Stew", image_url: null },
        ],
        total: 3,
      },
      isError: false,
      refetch: vi.fn(),
    });
  }

  it("keeps both lists mounted in one grid cell, so the sheet does not jump between tabs", () => {
    twoLists();
    renderModal();

    // The shorter list used to size the sheet on its tab and the longer one
    // on the other, so the dialog moved on every switch. Both stay in the
    // layout, one over the other, and the cell is as tall as the taller.
    const panels = screen.getAllByRole("tabpanel", { hidden: true });
    expect(panels).toHaveLength(2);
    for (const panel of panels) {
      expect(panel.className).toContain("col-start-1");
      expect(panel.parentElement?.className).toContain("grid");
    }
  });

  it("opens the other list at its top, not where this one was scrolled to", () => {
    twoLists();
    renderModal();
    const scroller = screen.getAllByRole("tabpanel", { hidden: true })[0]
      .parentElement?.parentElement as HTMLElement;
    scroller.scrollTop = 120;

    fireEvent.mouseDown(screen.getByRole("tab", { name: "All Recipes" }));

    expect(scroller.scrollTop).toBe(0);
  });
});

describe("RecipePickerModal — the All Recipes tab states what is on the shelf", () => {
  it("writes the same coverage on a listed recipe as the suggestions do", () => {
    mocks.useMealPlanSuggestions.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    mocks.useRecipes.mockReturnValue({
      data: {
        items: [
          {
            id: "r1",
            name: "Soup",
            image_url: null,
            ingredients_available: 2,
            ingredients_total: 5,
          },
          {
            id: "r2",
            name: "Water",
            image_url: null,
            ingredients_available: 0,
            ingredients_total: 0,
          },
        ],
        total: 2,
      },
      isError: false,
      refetch: vi.fn(),
    });
    renderModal();

    const soup = screen.getByRole("button", { name: /Soup/ });
    expect(soup).toHaveTextContent(/2/);
    expect(soup).toHaveTextContent(/5/);
    // A recipe with no counted ingredients has nothing to state.
    expect(screen.getByRole("button", { name: /Water/ })).not.toHaveTextContent(
      /\d/,
    );
  });
});
