import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import NutritionCard from "./NutritionCard";
import ServingsSelector from "./ServingsSelector";
import PickingItemRow from "./PickingItemRow";
import PickingIdlePhase from "./PickingIdlePhase";
import RecipeNutritionSection from "./RecipeNutritionSection";
import type { PickingItem } from "@/modules/recipes/types/core";
import type { RecipeNutrition } from "@/modules/recipes/types/nutrition";
import { tFor } from "@/test/mocks/i18n";

vi.mock("../hooks/useRecipes", () => ({
  useRecipeNutrition: vi.fn(() => ({
    isLoading: false,
    isFetched: false,
    data: undefined,
  })),
  useRecipeAvailability: vi.fn(() => ({
    isLoading: false,
    isFetching: false,
    data: undefined,
    refetch: vi.fn(),
  })),
  useAddToShoppingList: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
  useRecipeHistory: vi.fn(() => ({
    isLoading: false,
    data: undefined,
  })),
  usePatchCookingHistory: vi.fn(() => ({
    mutateAsync: vi.fn(),
  })),
}));

const noop = vi.fn();

const mockNutrition: RecipeNutrition = {
  warnings: [],
  scale: 1,
  recipe_id: "recipe-1",
  servings: 4,
  per_serving: {
    calories_kcal: 350,
    protein_g: 20,
    fat_g: 10,
    carbs_g: 45,
    fiber_g: 5,
    sugar_g: 8,
    salt_g: 1.2,
  },
  total: {
    calories_kcal: 1400,
    protein_g: 80,
    fat_g: 40,
    carbs_g: 180,
    fiber_g: 20,
    sugar_g: 32,
    salt_g: 4.8,
  },
  ingredients: [],
  coverage: 0.9,
  missing_nutrition: [],
  generic_values: false,
};

// ─── NutritionCard ────────────────────────────────────────────────────────────

describe("NutritionCard", () => {
  it("renders calorie value", () => {
    render(<NutritionCard data={mockNutrition} servings={4} />);
    expect(screen.getByText("350")).toBeInTheDocument();
  });

  it("renders macro values as grams", () => {
    render(<NutritionCard data={mockNutrition} servings={4} />);
    expect(screen.getByText("20.0g")).toBeInTheDocument(); // protein
  });

  it("renders dash when calories_kcal is null", () => {
    const noCalData: RecipeNutrition = {
      ...mockNutrition,
      per_serving: {
        ...mockNutrition.per_serving,
        calories_kcal: null as unknown as number,
      },
    };
    render(<NutritionCard data={noCalData} servings={1} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// ─── ServingsSelector ─────────────────────────────────────────────────────────

describe("ServingsSelector", () => {
  it("renders the current servings value", () => {
    render(<ServingsSelector value={4} onChange={noop} label="Servings" />);
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("calls onChange with incremented value when + clicked", () => {
    const onChange = vi.fn();
    render(<ServingsSelector value={3} onChange={onChange} label="Servings" />);
    fireEvent.click(screen.getByText("+"));
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it("calls onChange with decremented value when − clicked", () => {
    const onChange = vi.fn();
    render(<ServingsSelector value={3} onChange={onChange} label="Servings" />);
    fireEvent.click(screen.getByText("−"));
    expect(onChange).toHaveBeenCalledWith(2);
  });

  it("does not decrement below 1", () => {
    const onChange = vi.fn();
    render(<ServingsSelector value={1} onChange={onChange} label="Servings" />);
    fireEvent.click(screen.getByText("−"));
    expect(onChange).toHaveBeenCalledWith(1);
  });

  it("shows cleanHint when provided", () => {
    render(
      <ServingsSelector
        value={2}
        onChange={noop}
        label="Servings"
        cleanHint="Clean serving count"
      />,
    );
    expect(screen.getByText("Clean serving count")).toBeInTheDocument();
  });
});

// ─── PickingItemRow ───────────────────────────────────────────────────────────

const makePicking = (
  status: PickingItem["status"],
  recommendedItemId: string | null = "item-1",
): PickingItem => ({
  ingredient_id: "ing-1",
  name: "Flour",
  quantity_to_pick: 2,
  uom_symbol: "kg",
  recommended_item_id: recommendedItemId,
  location: "Pantry",
  fefo_days_left: null,
  fefo_expiry_date: null,
  status,
  is_linked: true,
});

describe("PickingItemRow", () => {
  it("renders ingredient name", () => {
    render(
      <PickingItemRow
        item={makePicking("pending")}
        onTap={noop}
        onUndo={noop}
      />,
    );
    expect(screen.getByText("Flour")).toBeInTheDocument();
  });

  it("renders quantity and uom", () => {
    render(
      <PickingItemRow
        item={makePicking("pending")}
        onTap={noop}
        onUndo={noop}
      />,
    );
    // fmtQty(2) = "2", uom = "kg" — rendered as combined "2 kg" in one span
    expect(screen.getByText(/2.*kg/)).toBeInTheDocument();
  });

  it("calls onTap when pending row clicked", () => {
    const onTap = vi.fn();
    render(
      <PickingItemRow
        item={makePicking("pending")}
        onTap={onTap}
        onUndo={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onTap).toHaveBeenCalled();
  });

  it("calls onUndo when picked row clicked", () => {
    const onUndo = vi.fn();
    render(
      <PickingItemRow
        item={makePicking("picked")}
        onTap={noop}
        onUndo={onUndo}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onUndo).toHaveBeenCalled();
  });

  it("is not a button when status is skipped", () => {
    render(
      <PickingItemRow
        item={makePicking("skipped")}
        onTap={noop}
        onUndo={noop}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// ─── PickingIdlePhase ─────────────────────────────────────────────────────────

// Real translator: an identity stub would let every label assertion
// below pass against a missing translation.
const tMock = tFor("recipes");

describe("PickingIdlePhase", () => {
  const defaultProps = {
    recipeName: "Spaghetti Bolognese",
    servings: 4,
    onServingsChange: noop,
    cleanServingsHint: null,
    isLoading: false,
    error: null,
    onStart: noop,
    onClose: noop,
    t: tMock,
  };

  it("renders the recipe name", () => {
    render(<PickingIdlePhase {...defaultProps} />);
    expect(screen.getByText("Spaghetti Bolognese")).toBeInTheDocument();
  });

  it("renders start and cancel buttons", () => {
    render(<PickingIdlePhase {...defaultProps} />);
    expect(screen.getByText("Take from stock")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("calls onClose when cancel is clicked", () => {
    const onClose = vi.fn();
    render(<PickingIdlePhase {...defaultProps} onClose={onClose} />);
    fireEvent.click(screen.getAllByText("Cancel")[0]);
    expect(onClose).toHaveBeenCalled();
  });

  it("shows error message when error is provided", () => {
    render(<PickingIdlePhase {...defaultProps} error="Something went wrong" />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("offers the start whatever the ingredients are linked to", () => {
    // A recipe with no links at all still picks by name, so the sheet has
    // no business refusing to start — the truth about stock comes after.
    render(<PickingIdlePhase {...defaultProps} />);
    expect(screen.getByText("Take from stock")).toBeInTheDocument();
  });
});

// ─── RecipeNutritionSection ───────────────────────────────────────────────────

describe("RecipeNutritionSection", () => {
  it("renders the toggle button", () => {
    render(<RecipeNutritionSection recipeId="recipe-1" activeServings={2} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeInTheDocument();
  });

  it("shows nutrition title in toggle button", () => {
    render(<RecipeNutritionSection recipeId="recipe-1" activeServings={2} />);
    expect(screen.getByText("Nutrition")).toBeInTheDocument();
  });

  it("does not show NutritionCard before toggle", () => {
    render(<RecipeNutritionSection recipeId="recipe-1" activeServings={2} />);
    // NutritionCard is only rendered after toggling
    expect(screen.queryByText(/kcal/i)).toBeNull();
  });
});
