import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import { signInWith, signOut } from "@/test/auth";
import { IngredientPriceEditor } from "./IngredientPriceEditor";

const setPrice = vi.hoisted(() => vi.fn());

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useSetIngredientPrice: () => ({ mutateAsync: setPrice, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderEditor(
  props?: Partial<React.ComponentProps<typeof IngredientPriceEditor>>,
) {
  render(
    <QueryWrapper>
      <IngredientPriceEditor
        templateId="tpl-lye"
        unit="kg"
        price={null}
        inUse
        canManage
        {...props}
      />
    </QueryWrapper>,
  );
}

describe("IngredientPriceEditor", () => {
  beforeEach(() => {
    setPrice.mockReset();
    setPrice.mockResolvedValue({
      product_template_id: "tpl-lye",
      unit_price: "8.25",
    });
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  it("types a price for an ingredient the records do not price", async () => {
    renderEditor();
    fireEvent.click(screen.getByTestId("maker-ingredient-price-edit"));
    fireEvent.change(screen.getByTestId("maker-ingredient-price-input"), {
      target: { value: "8.25" },
    });
    fireEvent.click(screen.getByTestId("maker-ingredient-price-save"));

    await waitFor(() =>
      expect(setPrice).toHaveBeenCalledWith({
        templateId: "tpl-lye",
        unitPrice: "8.25",
      }),
    );
  });

  it("shows the typed price on the ingredient's card", () => {
    renderEditor({ price: "8.25" });
    const figure = screen.getByTestId("maker-ingredient-typed-price");
    expect(figure.textContent).toContain("8.25");
    expect(figure.textContent).toContain("/ kg");
    expect(
      screen.queryByTestId("maker-ingredient-typed-price-unused"),
    ).not.toBeInTheDocument();
  });

  it("says when the typed price is not the one the estimate uses", () => {
    // The layer and the supplier quote answer first, so a typed price can sit
    // on a product while another number prices the line. Shown plainly, the
    // card read as if the typed price were the cost.
    renderEditor({ price: "8.25", inUse: false });
    expect(
      screen.getByTestId("maker-ingredient-typed-price-unused"),
    ).toHaveTextContent(/stock cost or supplier price/i);
  });

  it("clears the price instead of leaving a stale number behind", async () => {
    renderEditor({ price: "8.25" });
    fireEvent.click(screen.getByTestId("maker-ingredient-price-edit"));
    fireEvent.change(screen.getByTestId("maker-ingredient-price-input"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByTestId("maker-ingredient-price-save"));

    await waitFor(() =>
      expect(setPrice).toHaveBeenCalledWith({
        templateId: "tpl-lye",
        unitPrice: null,
      }),
    );
  });

  it("offers no edit to an account that may not change the formula", () => {
    renderEditor({ canManage: false });
    expect(
      screen.queryByTestId("maker-ingredient-price-edit"),
    ).not.toBeInTheDocument();
  });
});
