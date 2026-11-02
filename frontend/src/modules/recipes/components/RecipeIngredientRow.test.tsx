import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RecipeIngredientRow, {
  type IngredientDraft,
} from "./RecipeIngredientRow";
import type { IngredientStockUnit } from "@/modules/recipes/hooks/useIngredientStockUnits";

// The row says the narrowing rule itself, at its own width; the picker is
// a stub here.
vi.mock("@/modules/shared/components/UomSelect", () => ({
  UomSelect: () => <div data-testid="uom-select" />,
}));
// The row asks the catalogue for the unit of the ingredient's stock unit, and
// its category to tell a counted unit from a kilogram. The real `isCountedUom`
// is kept, so the category rule under test is the shipped one.
const uomCatalogue = vi.hoisted(() => ({
  failed: false,
  flat: [] as Array<{ id: string; symbol: string }>,
  categories: [] as Array<{
    id: string;
    name: string;
    uoms: Array<{ id: string; symbol: string }>;
  }>,
}));
vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/shared/hooks/useUoms")>();
  return {
    ...actual,
    useFlatUoms: () => ({
      data: uomCatalogue.failed ? undefined : uomCatalogue.flat,
      isError: uomCatalogue.failed,
    }),
    useUoms: () => ({
      data: uomCatalogue.failed ? undefined : uomCatalogue.categories,
      isLoading: false,
      isError: uomCatalogue.failed,
    }),
  };
});

afterEach(() => {
  uomCatalogue.failed = false;
  uomCatalogue.flat = [];
  uomCatalogue.categories = [];
});
vi.mock("./ExclusionToggle", () => ({
  ExclusionToggle: () => <div data-testid="exclusion-toggle" />,
}));
vi.mock("./AllergenPicker", () => ({
  AllergenPicker: () => <div data-testid="allergen-picker" />,
}));
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

const draft: IngredientDraft = {
  sort_order: 0,
  _key: 1,
  name: "ryż",
  quantity: "200",
  uom_id: null,
  uom_symbol: null,
  calories_kcal_per_100g: "",
  price: "",
  is_optional: false,
  is_spice: false,
  picking_skip: null,
  template_id: null,
  allergens: [],
};

async function renderExpanded(
  ing: Partial<IngredientDraft> = {},
  stockUnit?: IngredientStockUnit,
) {
  const user = userEvent.setup();
  render(
    <RecipeIngredientRow
      ing={{ ...draft, ...ing }}
      idx={0}
      errors={{}}
      onUpdate={vi.fn()}
      onRemove={vi.fn()}
      onNameBlur={vi.fn()}
      stockUnit={stockUnit}
    />,
  );
  // kcal and price live behind the row's "more options" disclosure.
  await user.click(screen.getByRole("button", { expanded: false }));
}

describe("RecipeIngredientRow — the unit beside a number", () => {
  it("names the calorie unit once while the field is still empty", async () => {
    await renderExpanded();

    // The suffix carries it; the placeholder used to say it a second time,
    // so an empty field read "kcal/100g   kcal/100g".
    expect(screen.getAllByText("kcal/100g")).toHaveLength(1);
    expect(
      screen.getByPlaceholderText("0"),
      "the calorie field asks for a number, not for its own unit",
    ).toBeInTheDocument();
  });

  it("names it once again when the field has a value", async () => {
    await renderExpanded({ calories_kcal_per_100g: "130" });

    expect(screen.getAllByText(/kcal\/100g/)).toHaveLength(1);
  });

  it("says just 'Price' for an ingredient with no unit chosen yet", async () => {
    await renderExpanded();

    // "Price per {{unit}}" has no unit to name, and the key that used to
    // stand in for one was never written — so it rendered as its own name.
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.queryByText(/form\.unit/)).not.toBeInTheDocument();
  });

  it("names the unit in the price label once the ingredient has one", async () => {
    await renderExpanded({ uom_symbol: "g" });

    expect(screen.getByText("Price per g")).toBeInTheDocument();
  });

  it("keeps the disclosure at a 44px touch target below md", () => {
    // Measured at 390x844: the chevron was 24x24 — smaller than the text
    // beside it and half the floor — in a row whose neighbours are fields a
    // thumb aims at, so a miss collapsed the wrong line. The size is stated
    // at the call site because `content` hands the height back by design.
    render(
      <RecipeIngredientRow
        ing={draft}
        idx={0}
        errors={{}}
        onUpdate={vi.fn()}
        onRemove={vi.fn()}
        onNameBlur={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { expanded: false })).toHaveClass(
      "min-h-11",
      "min-w-11",
      "md:min-h-0",
      "md:min-w-0",
    );
  });
});

describe("RecipeIngredientRow — the name row on a phone", () => {
  function renderRow() {
    render(
      <RecipeIngredientRow
        ing={draft}
        idx={0}
        errors={{}}
        onUpdate={vi.fn()}
        onRemove={vi.fn()}
        onNameBlur={vi.fn()}
      />,
    );
  }

  it("lets the link chip and the actions drop to a second line instead of squeezing the name", () => {
    // Measured at 390x844: the name input was 72px wide beside the chip, the
    // chevron and the delete button in one line, so only 'Na' of the
    // placeholder showed. The name keeps a floor and the rest wraps.
    renderRow();

    const nameInput = screen.getByRole("textbox", {
      name: /ingredient name/i,
    });
    expect(nameInput.closest(".flex-wrap")).not.toBeNull();
    expect(nameInput.closest(".min-w-\\[14rem\\]")).not.toBeNull();
  });

  it("keeps the delete button at a 44px touch target below md", () => {
    renderRow();

    expect(screen.getByRole("button", { name: /^remove$/i })).toHaveClass(
      "min-h-11",
      "min-w-11",
      "md:min-h-0",
      "md:min-w-0",
    );
  });
});

describe("RecipeIngredientRow — a counted unit with nothing saying what it measures", () => {
  const pieceCatalogue = () => {
    uomCatalogue.categories = [
      {
        id: "cat-unit",
        name: "Unit",
        uoms: [{ id: "u-pcs", symbol: "pcs" }],
      },
    ];
    uomCatalogue.flat = [{ id: "u-pcs", symbol: "pcs" }];
  };

  it("points at the product card's weight or volume per piece", async () => {
    // The picker offered only "pcs." and the hint named the rule but not the
    // way out: the card's per-piece measure is what puts ml on one scale
    // with the stocked piece.
    pieceCatalogue();

    await renderExpanded({}, { uomId: "u-pcs", measureUomIds: [] });

    expect(screen.getByTestId("uom-convertible-hint")).toHaveTextContent(
      "per piece on the product card",
    );
  });

  it("does not name the stock unit by its id when the units failed to load", async () => {
    // The hint falls back to the unit's id when the catalogue has no symbol
    // for it, which is what a failed request looked like: "Only units
    // convertible into 3f2a… are offered."
    pieceCatalogue();
    uomCatalogue.failed = true;

    await renderExpanded({}, { uomId: "u-pcs", measureUomIds: ["u-ml"] });

    expect(screen.queryByTestId("uom-convertible-hint")).toBeNull();
  });

  it("says the measure's units are offered once the card carries it", async () => {
    // The sentence used to keep saying only the stock unit was offered while
    // the card's weight or volume made g and ml readable as it.
    pieceCatalogue();

    await renderExpanded({}, { uomId: "u-pcs", measureUomIds: ["u-ml"] });

    const hint = screen.getByTestId("uom-convertible-hint").textContent;
    expect(hint).toBe(
      "Offered: pcs and the units of the weight or volume per piece stated on the product card.",
    );
  });

  it("points at the card's measure for a bulk package too", async () => {
    // A pack is counted like a piece, and the card's weight or volume per
    // unit is the same bridge for it (ADR-015) — the way out must not stop
    // at the Unit category.
    uomCatalogue.categories = [
      {
        id: "cat-pack",
        name: "Pack",
        uoms: [{ id: "u-pack", symbol: "pack" }],
      },
    ];
    uomCatalogue.flat = [{ id: "u-pack", symbol: "pack" }];

    await renderExpanded({}, { uomId: "u-pack", measureUomIds: [] });

    expect(screen.getByTestId("uom-convertible-hint")).toHaveTextContent(
      "per piece on the product card",
    );
  });

  it("keeps a measured unit's plain rule — the card's measure is not its way out", async () => {
    // Length has a scale of its own; "enter weight or volume per piece"
    // would send the reader to a field that does not move a centimetre.
    uomCatalogue.categories = [
      {
        id: "cat-length",
        name: "Length",
        uoms: [{ id: "u-cm", symbol: "cm" }],
      },
    ];
    uomCatalogue.flat = [{ id: "u-cm", symbol: "cm" }];

    await renderExpanded({}, { uomId: "u-cm", measureUomIds: [] });

    const hint = screen.getByTestId("uom-convertible-hint").textContent;
    expect(hint).toBe("Only units convertible into cm are offered.");
  });
});
