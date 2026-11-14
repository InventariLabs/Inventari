import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { signInWith, signOut } from "@/test/auth";
import { RecipeShortageNotice } from "./RecipeShortageNotice";
import type { AvailabilityResponse } from "@/modules/maker/types/maker";

const orderShortages = vi.hoisted(() => vi.fn());
const addStock = vi.hoisted(() => vi.fn());

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useOrderRecipeShortages: () => ({
    mutateAsync: orderShortages,
    isPending: false,
  }),
  useAddIngredientStock: () => ({ mutateAsync: addStock, isPending: false }),
}));

vi.mock("@/modules/shared/hooks/useStorages", () => ({
  useStorages: () => ({
    data: [{ id: "loc-1", name: "Pantry" }],
    isLoading: false,
  }),
}));

const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

const availability: AvailabilityResponse = {
  has_shortage: true,
  has_unknown: false,
  max_batches: "0",
  ingredients: [
    {
      child_template_id: "tpl-lye",
      child_template_name: "Lye",
      needed: "1.5",
      available: "0",
      shortage: "1.5",
      uom_symbol: "kg",
      convertible: true,
      to_buy: "1.5",
      to_buy_uom_symbol: "kg",
    },
  ],
};

function renderNotice(
  props?: Partial<React.ComponentProps<typeof RecipeShortageNotice>>,
) {
  render(
    <RecipeShortageNotice
      recipeId="rec-1"
      availability={availability}
      canAddStock
      canOrder
      {...props}
    />,
  );
}

describe("RecipeShortageNotice", () => {
  beforeEach(() => {
    orderShortages.mockReset();
    addStock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    signInWith([
      "maker:read",
      "maker:write",
      "maker:manage",
      "items:write",
      "purchase_orders:write",
    ]);
  });

  afterEach(() => {
    signOut();
  });

  it("says at the top of the formula what the records do not hold", () => {
    renderNotice();
    const notice = screen.getByTestId("maker-recipe-shortage-notice");
    expect(notice.textContent).toContain("Lye");
    expect(notice.textContent).toContain("1.5 kg");
  });

  it("offers no way out that this account or this organization cannot use", () => {
    renderNotice({ canAddStock: false, canOrder: false });
    expect(
      screen.queryByTestId("maker-recipe-add-stock"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-recipe-order-shortage"),
    ).not.toBeInTheDocument();
  });

  it("orders the missing ingredients without leaving production", async () => {
    orderShortages.mockResolvedValue({
      purchase_order_id: "po-1",
      number: "PO/2026/0001",
      added_count: 1,
    });
    renderNotice();
    fireEvent.click(screen.getByTestId("maker-recipe-order-shortage"));

    await waitFor(() => expect(orderShortages).toHaveBeenCalledWith("rec-1"));
    expect(toastSuccess).toHaveBeenCalledWith(
      expect.stringContaining("PO/2026/0001"),
    );
  });

  it("adds the stock the user has, quantity and price, as one record per ingredient", async () => {
    addStock.mockResolvedValue(undefined);
    renderNotice();
    fireEvent.click(screen.getByTestId("maker-recipe-add-stock"));

    const quantity = screen.getByTestId("maker-add-stock-quantity");
    expect(quantity).toHaveValue(1.5);
    fireEvent.change(screen.getByTestId("maker-add-stock-price"), {
      target: { value: "12.00" },
    });
    fireEvent.click(screen.getByTestId("maker-add-stock-save"));

    await waitFor(() =>
      expect(addStock).toHaveBeenCalledWith({
        name: "Lye",
        template_id: "tpl-lye",
        location_id: "loc-1",
        quantity: "1.5",
        purchase_price: "12.00",
      }),
    );
    expect(toastSuccess).toHaveBeenCalled();
  });
});
