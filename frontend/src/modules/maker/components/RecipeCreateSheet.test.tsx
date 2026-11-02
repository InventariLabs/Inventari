import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RecipeCreateSheet } from "./RecipeCreateSheet";
import type { MakerRecipe, RecipeCreate } from "@/modules/maker/types/maker";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents_products";

interface CreateMutationOptions {
  onSuccess: (recipe: MakerRecipe) => void;
  onError: (err: Error) => void;
}

const createMutate =
  vi.fn<(payload: RecipeCreate, options: CreateMutationOptions) => void>();

const pickedSku = vi.hoisted(() => ({ value: "CB-1" }));
const pickedUom = vi.hoisted(() => ({ value: null as string | null }));
const searchFormUnit = vi.hoisted(() => ({
  value: undefined as { uomId: string | null; missingHint: string } | undefined,
}));

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useCreateMakerRecipe: () => ({ mutate: createMutate, isPending: false }),
}));

const units = vi.hoisted(() => ({ failed: false }));
const refetchUnits = vi.fn();

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () =>
    units.failed
      ? {
          data: undefined,
          isError: true,
          error: new Error("boom"),
          refetch: refetchUnits,
        }
      : {
          data: [
            { id: "uom-kg", name: "Kilogram", symbol: "kg" },
            { id: "uom-pcs", name: "Piece", symbol: "pcs" },
          ],
          isError: false,
          error: null,
          refetch: refetchUnits,
        },
}));

vi.mock("@/modules/maker/components/ProductSearchInput", () => ({
  ProductSearchInput: ({
    onSelect,
    formUnit,
  }: {
    onSelect: (product: ProductSearchResult) => void;
    formUnit?: { uomId: string | null; missingHint: string };
  }) => {
    searchFormUnit.value = formUnit;
    return (
      <button
        type="button"
        onClick={() =>
          onSelect({
            product_template_id: "tpl-1",
            name: "Cold Brew 1L",
            sku: pickedSku.value,
            barcode: null,
            brand: null,
            uom_id: pickedUom.value,
            uom_symbol: null,
            image_url: null,
            is_stub: false,
          })
        }
      >
        pick-product
      </button>
    );
  },
}));

function renderSheet(onSuccess = vi.fn()) {
  render(
    <MemoryRouter>
      <RecipeCreateSheet open onClose={vi.fn()} onSuccess={onSuccess} />
    </MemoryRouter>,
  );
  return onSuccess;
}

describe("RecipeCreateSheet", () => {
  afterEach(() => {
    pickedSku.value = "CB-1";
    pickedUom.value = null;
    createMutate.mockClear();
  });

  it("shows the picked product's SKU on the selected card", () => {
    renderSheet();
    fireEvent.click(screen.getByRole("button", { name: "pick-product" }));
    expect(screen.getByText("CB-1")).toBeInTheDocument();
  });

  it("does not print the SKU the server minted on the selected card", () => {
    pickedSku.value = "STM-CD4E8B75";
    renderSheet();
    fireEvent.click(screen.getByRole("button", { name: "pick-product" }));
    expect(screen.getAllByText("Cold Brew 1L").length).toBeGreaterThan(0);
    expect(screen.queryByText("STM-CD4E8B75")).not.toBeInTheDocument();
  });

  it("creates a formula with the picked product and defaults the name", () => {
    const onSuccess = renderSheet();
    fireEvent.click(screen.getByRole("button", { name: "pick-product" }));
    // Name field defaults to the product name.
    expect(screen.getByTestId("maker-recipe-create-name")).toHaveValue(
      "Cold Brew 1L",
    );

    fireEvent.click(screen.getByTestId("maker-recipe-create-submit"));

    expect(createMutate).toHaveBeenCalledWith(
      {
        output_template_id: "tpl-1",
        name: "Cold Brew 1L",
        batch_yield_qty: undefined,
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );

    const [, options] = createMutate.mock.calls[0];
    options.onSuccess({ id: "recipe-9" } as MakerRecipe);
    expect(onSuccess).toHaveBeenCalledWith("recipe-9");
  });

  it("sends an optional batch yield quantity", () => {
    renderSheet();
    fireEvent.click(screen.getByRole("button", { name: "pick-product" }));
    fireEvent.change(screen.getByTestId("maker-recipe-create-batch-yield"), {
      target: { value: "4" },
    });
    fireEvent.click(screen.getByTestId("maker-recipe-create-submit"));

    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        output_template_id: "tpl-1",
        batch_yield_qty: "4",
      }),
      expect.any(Object),
    );
  });

  it("hands the unit beside the quantity to the search's add-as-new panel", () => {
    renderSheet();
    // Nothing chosen yet: the panel is told where the unit is asked.
    expect(searchFormUnit.value).toEqual({
      uomId: null,
      missingHint: "Pick the unit next to the quantity first.",
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Unit" }), {
      target: { value: "uom-kg" },
    });
    expect(searchFormUnit.value?.uomId).toBe("uom-kg");
  });

  it("fixes the unit to the picked product's own and sends none of its own", () => {
    pickedUom.value = "uom-pcs";
    renderSheet();
    fireEvent.click(screen.getByRole("button", { name: "pick-product" }));
    const unit = screen.getByRole("combobox", { name: "Unit" });
    expect(unit).toHaveValue("uom-pcs");
    expect(unit).toBeDisabled();
    fireEvent.click(screen.getByTestId("maker-recipe-create-submit"));
    expect(createMutate.mock.calls[0][0].batch_yield_uom_id).toBeUndefined();
  });

  it("lets a product with no unit take the one chosen beside the quantity", () => {
    renderSheet();
    fireEvent.click(screen.getByRole("button", { name: "pick-product" }));
    const unit = screen.getByRole("combobox", { name: "Unit" });
    expect(unit).toBeEnabled();
    fireEvent.change(unit, { target: { value: "uom-kg" } });
    fireEvent.click(screen.getByTestId("maker-recipe-create-submit"));
    expect(createMutate.mock.calls[0][0].batch_yield_uom_id).toBe("uom-kg");
  });

  it("says the units did not load instead of offering an empty list", () => {
    units.failed = true;
    try {
      renderSheet();
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      expect(refetchUnits).toHaveBeenCalled();
    } finally {
      units.failed = false;
    }
  });

  it("does not submit without a picked product", () => {
    renderSheet();
    fireEvent.click(screen.getByTestId("maker-recipe-create-submit"));
    expect(createMutate).not.toHaveBeenCalled();
  });
});
