import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { signInWith, signOut } from "@/test/auth";
import RecipeIngredientsSection, {
  type IngredientDraft,
} from "./RecipeIngredientsSection";

// The "always at home" toggle on each row is `recipes:write`; these tests
// exercise the rows as a writer.
beforeEach(() => signInWith(["recipes:read", "recipes:write"]));
afterEach(() => {
  signOut();
  stockUnitsRead.failed = false;
  stockUnitsRead.refetch.mockClear();
});

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({ data: [] }),
  useUoms: () => ({ data: [], isLoading: false }),
  isCountedUom: () => false,
}));

// The section asks the catalogue which stock unit each linked ingredient
// keeps; these tests are about the row layout, not about the catalogue.
const stockUnitsRead = vi.hoisted(() => ({
  failed: false,
  refetch: vi.fn(),
}));
vi.mock("@/modules/recipes/hooks/useIngredientStockUnits", () => ({
  useIngredientStockUnits: () => ({
    stockUnits: {},
    isError: stockUnitsRead.failed,
    refetch: stockUnitsRead.refetch,
  }),
}));

vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useShoppingExclusions: () => ({ data: [], isLoading: false }),
  useCreateShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("./IngredientTemplateCombobox", () => ({
  default: (props: {
    query: string;
    onChange: (templateId: string | null, name: string) => void;
    onQueryChange: (v: string) => void;
    onBlur: () => void;
    error?: boolean;
    className?: string;
  }) => (
    <>
      <input
        aria-label="ingredient name"
        value={props.query}
        onChange={(e) => props.onQueryChange(e.target.value)}
        onBlur={props.onBlur}
      />
      <button
        type="button"
        aria-label="pick suggestion"
        onClick={() => props.onChange("tpl-9", "Wheat flour type 550")}
      >
        suggestion
      </button>
    </>
  ),
}));

vi.mock("@/modules/shared/components/UomSelect", () => ({
  UomSelect: (props: {
    value: string | null;
    onChange: (id: string) => void;
  }) => (
    <button
      type="button"
      aria-label="unit select"
      onClick={() => props.onChange("u1")}
    >
      unit
    </button>
  ),
}));

const draft = (overrides: Partial<IngredientDraft> = {}): IngredientDraft => ({
  _key: 0,
  name: "Tomato",
  template_id: null,
  quantity: "2",
  uom_id: null,
  uom_symbol: null,
  is_optional: false,
  is_spice: false,
  picking_skip: false,
  sort_order: 0,
  calories_kcal_per_100g: "",
  price: "",
  allergens: [],
  ...overrides,
});

const renderSection = (
  ingredients: IngredientDraft[],
  onUpdate: (...args: unknown[]) => void = vi.fn(),
) =>
  render(
    <RecipeIngredientsSection
      ingredients={ingredients}
      errors={{}}
      onUpdate={onUpdate as never}
      onRemove={vi.fn()}
      onAdd={vi.fn()}
      onNameBlur={vi.fn()}
    />,
  );

describe("RecipeIngredientsSection — simple by default, advanced on demand", () => {
  it("default row shows only name, quantity, unit and remove — no advanced fields", () => {
    renderSection([draft()]);
    expect(screen.getByLabelText("ingredient name")).toBeInTheDocument();
    expect(screen.getByLabelText("unit select")).toBeInTheDocument();
    expect(screen.getByLabelText("Remove")).toBeInTheDocument();
    // Advanced fields hidden until "More options"
    expect(screen.queryByText(/optional/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/kcal\/100g/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^price/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/always at home/i)).not.toBeInTheDocument();
  });

  it("reveals optional, kcal, price and always-at-home behind More options", () => {
    renderSection([draft()]);
    fireEvent.click(screen.getByRole("button", { name: /more options/i }));
    expect(screen.getByText(/optional/i)).toBeInTheDocument();
    expect(screen.getByText(/kcal\/100g/i)).toBeInTheDocument();
    // No unit chosen yet, so there is no "per" to name — the row says
    // "Price" until one is picked.
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText(/always at home/i)).toBeInTheDocument();
  });

  it("shows price per unit when a unit symbol is set", () => {
    renderSection([draft({ uom_symbol: "kg" })]);
    fireEvent.click(screen.getByRole("button", { name: /more options/i }));
    expect(screen.getByText(/price per kg/i)).toBeInTheDocument();
  });
});

describe("RecipeIngredientsSection — linking names the ingredient", () => {
  it("takes the product's name when a suggestion is picked", () => {
    // The typed fragment used to survive the link and reach the database,
    // so nutrition lookups, the shopping list and the shortage modal each
    // read a different name for the same thing.
    const onUpdate = vi.fn();
    renderSection([draft({ name: "Wheat fl" })], onUpdate);

    fireEvent.click(screen.getByRole("button", { name: "pick suggestion" }));

    expect(onUpdate).toHaveBeenCalledWith(0, "template_id", "tpl-9");
    expect(onUpdate).toHaveBeenCalledWith(0, "name", "Wheat flour type 550");
  });
});

describe("RecipeIngredientsSection — the stock units did not load", () => {
  it("says so and offers a retry instead of the free picker alone", () => {
    // Without the stock units every row offers all units and the refusal
    // comes at save; an empty map must not read as "nothing to restrict".
    stockUnitsRead.failed = true;
    renderSection([draft({ template_id: "tpl-1" })]);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(stockUnitsRead.refetch).toHaveBeenCalledTimes(1);
  });
});
