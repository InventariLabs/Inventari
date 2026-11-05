import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type Mock,
} from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { signInWith, signOut } from "@/test/auth";
import RecipeAvailabilityChecker from "./RecipeAvailabilityChecker";
import { toast } from "sonner";
import type { IngredientAvailability } from "@/modules/recipes/types/core";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock("../hooks/useMealPlans", () => ({
  useShoppingExclusions: () => ({ data: [], isLoading: false }),
  useCreateShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
}));

const availabilityData: {
  recipe_id: string;
  servings: number;
  ingredients: IngredientAvailability[];
} = {
  recipe_id: "r1",
  servings: 4,
  ingredients: [
    {
      ingredient_id: "i1",
      name: "Tomatoes",
      required_quantity: 2,
      required_uom: "kg",
      status: "missing",
      match_type: null,
      is_linked: false,
      is_spice: false,
      quantities_comparable: true,
      available_quantity: null,
      available_uom: null,
      best_item: null,
      alternative_items: [],
      display_text: null,
      original_quantity: null,
      original_unit_text: null,
      excluded: false,
    } satisfies IngredientAvailability,
  ],
};

const mockAddToShoppingList = vi.fn();
const mockUseActiveShoppingListId = vi.fn();

vi.mock("../hooks/useRecipes", () => ({
  useRecipeAvailability: () => ({
    isLoading: false,
    isFetching: false,
    data: availabilityData,
    refetch: vi.fn(),
  }),
  useAddToShoppingList: () => ({
    mutateAsync: mockAddToShoppingList,
    isPending: false,
  }),
  useLinkIngredientTemplate: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useActiveShoppingListId: () => mockUseActiveShoppingListId(),
}));

const modulesMock = vi.hoisted(() => ({ shoppingListsEnabled: true }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: modulesMock.shoppingListsEnabled ? ["shopping_lists"] : [],
    isModuleEnabled: (name: string) =>
      name === "shopping_lists" && modulesMock.shoppingListsEnabled,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

describe("RecipeAvailabilityChecker — shopping list toast", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Adding to a shopping list writes through `recipes:write`.
    signInWith(["recipes:read", "recipes:write"]);
    modulesMock.shoppingListsEnabled = true;
    mockUseActiveShoppingListId.mockReturnValue({ data: null });
    availabilityData.ingredients = [
      {
        ingredient_id: "i1",
        name: "Tomatoes",
        required_quantity: 2,
        required_uom: "kg",
        status: "missing",
        match_type: null,
        is_linked: false,
        is_spice: false,
        quantities_comparable: true,
        available_quantity: null,
        available_uom: null,
        best_item: null,
        alternative_items: [],
        display_text: null,
        original_quantity: null,
        original_unit_text: null,
        excluded: false,
      } satisfies IngredientAvailability,
    ];
  });

  it("exposes aria-expanded on the spices toggle", () => {
    availabilityData.ingredients = [
      ...availabilityData.ingredients,
      {
        ingredient_id: "i2",
        name: "Salt",
        required_quantity: 5,
        required_uom: "g",
        status: "available",
        match_type: null,
        is_linked: false,
        is_spice: false,
        quantities_comparable: true,
        available_quantity: null,
        available_uom: null,
        best_item: null,
        alternative_items: [],
        display_text: null,
        original_quantity: null,
        original_unit_text: null,
        excluded: false,
      } satisfies IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("button", { name: /seasonings/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps a one-piece ingredient among the main ingredients", () => {
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        ingredient_id: "i-egg",
        name: "Egg",
        required_quantity: 1,
        required_uom: "pcs",
      },
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    // One egg is not seasoning: the card used to fold every countable
    // ingredient at one or less into the collapsed spices section.
    expect(screen.getByText("Egg")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /seasonings/i }),
    ).not.toBeInTheDocument();
  });

  it("folds a marked piece into the seasonings section", () => {
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        ingredient_id: "i-bay",
        name: "Bay leaf",
        required_quantity: 1,
        required_uom: "pcs",
        status: "available",
        // One bay leaf is not a spice by amount — the cook marked it one in
        // the import review, and that mark travels on the ingredient.
        is_spice: true,
      },
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    // Not in the main list…
    expect(screen.queryByText("Bay leaf")).not.toBeInTheDocument();
    // …it is under the seasonings, which the amount alone would not do.
    fireEvent.click(screen.getByRole("button", { name: /seasonings/i }));
    expect(screen.getByText("Bay leaf")).toBeInTheDocument();
  });

  it("keeps a seasoning that is missing out of the folded section", () => {
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        ingredient_id: "i-salt",
        name: "Salt",
        required_quantity: 5,
        required_uom: "g",
        status: "missing",
      },
      {
        ...availabilityData.ingredients[0],
        ingredient_id: "i-pepper",
        name: "Pepper",
        required_quantity: 2,
        required_uom: "g",
        status: "available",
      },
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    // The one the footer counts as missing is named without a click…
    expect(screen.getByText("Salt")).toBeInTheDocument();
    // …the one on the shelf stays behind the fold.
    expect(screen.queryByText("Pepper")).not.toBeInTheDocument();
  });

  it("explains what the unknown legend entry means", () => {
    availabilityData.ingredients = [
      ...availabilityData.ingredients,
      {
        ingredient_id: "i3",
        name: "Cardamom",
        required_quantity: 2,
        required_uom: "g",
        status: "unknown",
        match_type: null,
        is_linked: false,
        is_spice: false,
        quantities_comparable: true,
        available_quantity: null,
        available_uom: null,
        best_item: null,
        alternative_items: [],
        display_text: null,
        original_quantity: null,
        original_unit_text: null,
        excluded: false,
      } satisfies IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/not linked to stock: 1/i)).toBeInTheDocument();
  });

  it("disables Add missing when nothing is missing", () => {
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        status: "available",
      } as IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: /add missing/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title");
  });

  it("disables Add missing when every missing ingredient is Always at home", () => {
    // Measured live: Fresh Basil on the exclusions list was the only
    // ingredient off the shelf — the legend said "Missing 1", the button
    // was live, and the click added 0 lines. The door reads the same
    // verdict the list rule applies.
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        name: "Fresh Basil",
        status: "missing",
        excluded: true,
      } as IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: /add missing/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title");
  });

  it("keeps Add missing live while a missing ingredient is not Always at home", () => {
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        name: "Fresh Basil",
        status: "missing",
        excluded: true,
      } as IngredientAvailability,
      {
        ingredient_id: "i2",
        name: "Parmesan",
        required_quantity: 100,
        required_uom: "g",
        status: "missing",
        match_type: null,
        is_linked: false,
        quantities_comparable: true,
        available_quantity: null,
        available_uom: null,
        best_item: null,
        alternative_items: [],
        display_text: null,
        original_quantity: null,
        original_unit_text: null,
        is_spice: false,
        excluded: false,
      } satisfies IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /add missing/i })).toBeEnabled();
  });

  it("keeps Add missing live when an ingredient is insufficient", () => {
    // The button and the backend's line share one predicate: a short
    // ingredient leaves something to buy.
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        status: "insufficient",
      } as IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /add missing/i })).toBeEnabled();
  });

  it("closes Add missing when the only stock found by name covers the recipe", () => {
    // "Similar" stock covers the ingredient, as the meal plan counts it:
    // the backend adds no line for it, so the door must not open over a
    // click that would add none.
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        status: "available_approx",
      } as IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/similar 1/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add missing/i })).toBeDisabled();
  });

  it("names the Not enough status in the legend", () => {
    availabilityData.ingredients = [
      {
        ...availabilityData.ingredients[0],
        status: "insufficient",
        available_quantity: 1,
      } as IngredientAvailability,
    ];
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/not enough 1/i)).toBeInTheDocument();
  });

  it("renders toast with list name when backend provides it", async () => {
    mockAddToShoppingList.mockResolvedValue({
      shopping_list_id: "sl1",
      added_count: 3,
      list_name: "Week 30",
    });
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add missing/i }));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalled());
    const message = (toast.success as Mock).mock.calls[0][0];
    expect(message).toContain("3");
    expect(message).toContain("Week 30");
    expect(message).not.toContain("{{");
  });

  // Pressed a second time, the button answered "Added 0 items to list …",
  // which reads as "nothing was missing" or as a failure. Everything it
  // would add is already on that list, and the toast says so.
  it("says the missing goods are already on the list instead of adding 0", async () => {
    mockAddToShoppingList.mockResolvedValue({
      shopping_list_id: "sl1",
      added_count: 0,
      already_listed_count: 2,
      list_name: "Shopping list",
    });
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add missing/i }));
    await vi.waitFor(() => expect(toast.info).toHaveBeenCalled());
    const message = (toast.info as Mock).mock.calls[0][0];
    expect(message).toMatch(/already/i);
    expect(message).toContain("Shopping list");
    expect(message).not.toMatch(/Added 0/);
    expect(toast.success).not.toHaveBeenCalled();
  });

  // The same goods on two open lists is two trips for one purchase; the
  // list is still written, and a second toast names where else they stand.
  it("names the other open list that already asks for the same goods", async () => {
    mockAddToShoppingList.mockResolvedValue({
      shopping_list_id: "sl2",
      added_count: 2,
      list_name: "Shopping list",
      on_other_lists: [
        { name: "Flour", list_id: "sl1", list_name: "Week 30" },
        { name: "Eggs", list_id: "sl1", list_name: "Week 30" },
      ],
    });
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add missing/i }));
    await vi.waitFor(() => expect(toast.warning).toHaveBeenCalled());
    const message = (toast.warning as Mock).mock.calls[0][0];
    expect(message).toContain("Flour, Eggs");
    expect(message).toContain("Week 30");
    expect(message).not.toContain("{{");
  });

  it("renders toast without raw placeholder when list_name is absent", async () => {
    mockAddToShoppingList.mockResolvedValue({
      shopping_list_id: "sl1",
      added_count: 1,
    });
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add missing/i }));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalled());
    const message = (toast.success as Mock).mock.calls[0][0];
    expect(message).toContain("1");
    expect(message).not.toContain("{{");
    expect(message).not.toContain("Week 30");
  });

  it("reuses the active shopping list instead of creating a new one", async () => {
    mockUseActiveShoppingListId.mockReturnValue({ data: "active-1" });
    mockAddToShoppingList.mockResolvedValue({
      shopping_list_id: "active-1",
      added_count: 1,
    });
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add missing/i }));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(mockAddToShoppingList).toHaveBeenCalledWith({
      servings: 4,
      shopping_list_id: "active-1",
    });
  });

  it("leaves shopping_list_id empty when no active list exists", async () => {
    mockUseActiveShoppingListId.mockReturnValue({ data: null });
    mockAddToShoppingList.mockResolvedValue({
      shopping_list_id: "new-1",
      added_count: 1,
    });
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add missing/i }));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalled());
    // Backend creates the first list when no id is sent.
    expect(mockAddToShoppingList).toHaveBeenCalledWith({ servings: 4 });
  });

  it("hides the shopping-list action when the shopping_lists module is disabled", () => {
    modulesMock.shoppingListsEnabled = false;
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /add missing/i }),
    ).not.toBeInTheDocument();
  });

  it("hides the shopping-list action from a reader", () => {
    // The button writes through `recipes:write`; it used to be offered to
    // every reader on an installation that has the module.
    signOut();
    render(
      <RecipeAvailabilityChecker
        recipeId="r1"
        activeServings={4}
        onServingsChange={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /add missing/i }),
    ).not.toBeInTheDocument();
  });
});

afterEach(signOut);
