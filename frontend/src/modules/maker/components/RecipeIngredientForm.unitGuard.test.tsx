import { render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { RecipeIngredientForm } from "./RecipeIngredientForm";
import { recipeApi } from "@/modules/maker/api/recipes";

// i18next is mocked globally and answers with the key where it has no
// translation, so the assertions below read the keys the component names.

const GRAM = "u1";
const KILOGRAM = "u2";
const PIECE = "u3";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/modules/maker/api/recipes", () => ({
  recipeApi: { addBomLine: vi.fn() },
}));

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: [
      { id: GRAM, symbol: "g", name: "Gram", category_id: "c1", factor: 1 },
      {
        id: KILOGRAM,
        symbol: "kg",
        name: "Kilogram",
        category_id: "c1",
        factor: 1000,
      },
      { id: PIECE, symbol: "pcs", name: "Piece", category_id: "c2", factor: 1 },
    ],
  }),
  useUoms: () => ({
    data: [
      {
        id: "c1",
        name: "Weight",
        uoms: [
          {
            id: GRAM,
            symbol: "g",
            name: "Gram",
            category_id: "c1",
            factor: 1,
          },
          {
            id: KILOGRAM,
            symbol: "kg",
            name: "Kilogram",
            category_id: "c1",
            factor: 1000,
          },
        ],
      },
      {
        id: "c2",
        name: "Count",
        uoms: [
          {
            id: PIECE,
            symbol: "pcs",
            name: "Piece",
            category_id: "c2",
            factor: 1,
          },
        ],
      },
    ],
    isLoading: false,
  }),
}));

// The product the reader picks: kept in grams, so the picker below it may
// only offer units that convert into grams.
vi.mock("@/modules/maker/components/ProductSearchInput", () => ({
  ProductSearchInput: ({
    onSelect,
    defaultUomId,
    label,
  }: {
    onSelect: (p: {
      product_template_id: string;
      name: string;
      uom_id: string;
      uom_symbol: string | null;
    }) => void;
    defaultUomId?: string | null;
    label?: string;
  }) => (
    <>
      <button
        type="button"
        data-testid="product-picker"
        onClick={() =>
          onSelect({
            product_template_id: "tpl-1",
            name: "Rye flour",
            uom_id: GRAM,
            uom_symbol: null,
          })
        }
      >
        {label ?? "pick a product"}
      </button>
      <span data-testid="product-default-uom">{defaultUomId ?? ""}</span>
    </>
  ),
}));

describe("RecipeIngredientForm — the units the guard will take", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("follows the picked product's unit and offers only convertible ones", async () => {
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    await user.click(screen.getByTestId("product-picker"));

    // The picked product is kept in grams, so pieces are not on the table:
    // the maker cannot read a line in pieces as grams and refuses it.
    await waitFor(() =>
      expect(screen.getByTestId("uom-convertible-hint")).toBeInTheDocument(),
    );
    // The hint names the unit the line has to be readable as. i18next is
    // mocked to answer with the raw key, so the interpolation itself is not
    // observable here — the presence of the hint is, and the picker's own
    // restriction is pinned in UomSelect.test.tsx.
    expect(screen.getByTestId("uom-convertible-hint").textContent).not.toBe("");
  });

  it("pre-fills nothing from the catalogue before a product is picked", async () => {
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    // The first catalogue unit used to be pre-filled here. It is a unit
    // nobody chose, and once a product is picked the guard may well refuse
    // it — so the picker starts empty and the Add button stays off until
    // both a product and a unit are on the line.
    expect(screen.getByTestId("product-default-uom").textContent).toBe("");
    expect(screen.getByTestId("maker-composition-add-line")).toBeDisabled();

    await user.click(screen.getByTestId("product-picker"));
    await waitFor(() =>
      expect(screen.getByTestId("maker-composition-add-line")).toBeEnabled(),
    );
  });

  it("follows the newly picked product's unit, not the previous one's", async () => {
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    await user.click(screen.getByTestId("product-picker"));

    // The pick is on the line, and the picker below it followed the
    // product's own unit — the stale unit a product change used to leave
    // behind is gone with the fallback that created it.
    await waitFor(() =>
      expect(
        screen.getByTestId("maker-composition-child-selected"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("maker-composition-add-line")).toBeEnabled();
  });
});

describe("RecipeIngredientForm — the add still goes through", () => {
  it("posts the line with the unit the picker holds", async () => {
    vi.mocked(recipeApi.addBomLine).mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    await user.click(screen.getByTestId("product-picker"));
    await waitFor(() =>
      expect(screen.getByTestId("maker-composition-add-line")).toBeEnabled(),
    );
    await user.click(screen.getByTestId("maker-composition-add-line"));

    expect(recipeApi.addBomLine).toHaveBeenCalledOnce();
    const call = vi.mocked(recipeApi.addBomLine).mock.calls[0];
    expect(call[1]).toMatchObject({ uom_id: GRAM, unit: "g" });
  });
});
