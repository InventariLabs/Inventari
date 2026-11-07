import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RecipeIngredientRow, {
  type IngredientDraft,
} from "./RecipeIngredientRow";
import type { IngredientStockUnit } from "@/modules/recipes/hooks/useIngredientStockUnits";

// The real picker, so the test reads what a cook is actually offered: a
// product kept in packs, whose card may or may not state a weight per pack.
const uom = (id: string, symbol: string, category_id: string) => ({
  id,
  name: `${symbol} name`,
  symbol,
  category_id,
  factor: "1",
  rounding: "0.001",
  is_reference: true,
  is_system: true,
});
const catalogue = vi.hoisted(() => ({ categories: [] as unknown[] }));
vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/shared/hooks/useUoms")>();
  return {
    ...actual,
    useFlatUoms: () => ({
      data: (
        catalogue.categories as Array<{ uoms: Array<{ id: string }> }>
      ).flatMap((c) => c.uoms),
      isError: false,
    }),
    useUoms: () => ({
      data: catalogue.categories,
      isLoading: false,
      isError: false,
    }),
  };
});
catalogue.categories = [
  { id: "c-pack", name: "Pack", uoms: [uom("u-pack", "pack", "c-pack")] },
  {
    id: "c-w",
    name: "Weight",
    uoms: [uom("u-g", "g", "c-w"), uom("u-kg", "kg", "c-w")],
  },
  {
    id: "c-v",
    name: "Volume",
    uoms: [uom("u-ml", "ml", "c-v"), uom("u-l", "l", "c-v")],
  },
  { id: "c-len", name: "Length", uoms: [uom("u-m", "m", "c-len")] },
];
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));
vi.mock("./ExclusionToggle", () => ({ ExclusionToggle: () => null }));
vi.mock("./AllergenPicker", () => ({ AllergenPicker: () => null }));

const draft: IngredientDraft = {
  sort_order: 0,
  _key: 1,
  name: "Rice 1 kg",
  quantity: "100",
  uom_id: null,
  uom_symbol: null,
  calories_kcal_per_100g: "",
  price: "",
  is_optional: false,
  is_spice: false,
  picking_skip: null,
  template_id: "tpl-rice",
  allergens: [],
};

async function offeredUnits(stockUnit: IngredientStockUnit) {
  const user = userEvent.setup();
  render(
    <RecipeIngredientRow
      ing={draft}
      idx={0}
      errors={{}}
      onUpdate={vi.fn()}
      onRemove={vi.fn()}
      onNameBlur={vi.fn()}
      stockUnit={stockUnit}
    />,
  );
  await user.click(screen.getByRole("button", { name: /choose/i }));
  await screen.findByTestId("uom-convertible-hint");
}

describe("RecipeIngredientRow — the units a linked ingredient offers", () => {
  it("offers g and kg beside the pack once the card states a weight per pack", async () => {
    // The cook set 1 kg per pack on the product card; the picker still
    // offered only "pack", so 100 g of rice could not be written.
    await offeredUnits({ uomId: "u-pack", measureUomIds: ["u-kg"] });

    expect(screen.getByText("pack")).toBeInTheDocument();
    expect(screen.getByText("g")).toBeInTheDocument();
    expect(screen.getByText("kg")).toBeInTheDocument();
    // The card says weight only: volume stays out, and so does length.
    expect(screen.queryByText("ml")).not.toBeInTheDocument();
    expect(screen.queryByText("m")).not.toBeInTheDocument();
    expect(screen.getByTestId("uom-convertible-hint")).toHaveTextContent(
      "the units of the weight or volume per piece",
    );
    // Said at the row's width, not squeezed into the unit's own column.
    expect(
      screen.getByTestId("uom-convertible-hint").closest(".w-28"),
    ).toBeNull();
  });

  it("offers ml and l beside the pack once the card states a volume per pack", async () => {
    // The hint already said "enter volume per piece to use ml"; once the card
    // carried it, the picker still left ml out.
    await offeredUnits({ uomId: "u-pack", measureUomIds: ["u-l"] });

    expect(screen.getByText("pack")).toBeInTheDocument();
    expect(screen.getByText("ml")).toBeInTheDocument();
    expect(screen.getByText("l")).toBeInTheDocument();
    expect(screen.queryByText("g")).not.toBeInTheDocument();
  });

  it("offers only the pack while the card states no measure, and points at the card", async () => {
    await offeredUnits({ uomId: "u-pack", measureUomIds: [] });

    expect(screen.getByText("pack")).toBeInTheDocument();
    expect(screen.queryByText("g")).not.toBeInTheDocument();
    expect(screen.queryByText("kg")).not.toBeInTheDocument();
    expect(screen.getByTestId("uom-convertible-hint")).toHaveTextContent(
      "Enter weight or volume per piece on the product card",
    );
  });
});
