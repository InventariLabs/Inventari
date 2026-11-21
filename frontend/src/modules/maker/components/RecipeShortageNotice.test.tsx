import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
    <MemoryRouter>
      <RecipeShortageNotice
        recipeId="rec-1"
        availability={availability}
        canAddStock
        canOrder
        {...props}
      />
    </MemoryRouter>,
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

describe("RecipeShortageNotice — a retry and a second order", () => {
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

  it("keeps only the rows that did not save when a later one fails", async () => {
    // Every row was kept after a failure, so the retry entered the stock that
    // had already been saved a second time. The saved rows leave the sheet.
    addStock
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(undefined);
    const twoIngredients: AvailabilityResponse = {
      ...availability,
      ingredients: [
        availability.ingredients[0],
        {
          ...availability.ingredients[0],
          child_template_id: "tpl-oil",
          child_template_name: "Oil",
        },
      ],
    };
    renderNotice({ availability: twoIngredients });
    fireEvent.click(screen.getByTestId("maker-recipe-add-stock"));
    fireEvent.click(screen.getByTestId("maker-add-stock-save"));

    await waitFor(() => expect(addStock).toHaveBeenCalledTimes(2));
    expect(toastError).toHaveBeenCalledWith(
      "Saved 1 of 2. The rest is still in the sheet.",
    );
    // The failed ingredient is the only one left, so a retry cannot enter
    // the saved one again.
    const rows = screen.getAllByTestId("maker-add-stock-row");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("Oil");
    expect(rows[0].textContent).not.toContain("Lye");

    fireEvent.click(screen.getByTestId("maker-add-stock-save"));
    await waitFor(() => expect(addStock).toHaveBeenCalledTimes(3));
    expect(addStock.mock.calls[2][0].template_id).toBe("tpl-oil");
  });

  it("says the shortage is already on an open order instead of ordering it again", async () => {
    orderShortages.mockResolvedValue({
      purchase_order_id: null,
      number: null,
      added_count: 0,
      already_ordered_count: 1,
    });
    renderNotice();
    fireEvent.click(screen.getByTestId("maker-recipe-order-shortage"));

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/already on an open purchase order/i),
      ),
    );
  });
});

describe("RecipeShortageNotice — a unit that does not match, and an order placed", () => {
  const mismatch: AvailabilityResponse = {
    ...availability,
    ingredients: [
      {
        ...availability.ingredients[0],
        child_template_id: "tpl-flour",
        child_template_name: "Wheat flour",
        shortage: null,
        to_buy: null,
      },
    ],
  };

  beforeEach(() => {
    orderShortages.mockReset();
    signInWith(["maker:read", "maker:write", "items:write"]);
  });

  afterEach(() => {
    signOut();
  });

  it("does not call a unit mismatch missing stock, and offers no stock for it", () => {
    renderNotice({ availability: mismatch });

    expect(
      screen.getByText("A unit on this BOM does not match the stock"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Not in the records/)).toBeNull();
    expect(screen.queryByTestId("maker-recipe-add-stock")).toBeNull();
    expect(screen.queryByTestId("maker-recipe-order-shortage")).toBeNull();
  });

  it("keeps the ways out for a real shortage that stands beside a mismatch", () => {
    renderNotice({
      availability: {
        ...availability,
        ingredients: [availability.ingredients[0], mismatch.ingredients[0]],
      },
    });

    expect(screen.getByText("Not in the records: Lye.")).toBeInTheDocument();
    expect(screen.getByTestId("maker-recipe-add-stock")).toBeInTheDocument();
  });

  it("says the missing quantity is on order, links the order and stops offering it", async () => {
    orderShortages.mockResolvedValue({
      purchase_order_id: "po-1",
      number: "PO/2026/0001",
      added_count: 1,
    });
    renderNotice();

    fireEvent.click(screen.getByTestId("maker-recipe-order-shortage"));

    expect(
      await screen.findByTestId("maker-recipe-on-order"),
    ).toHaveTextContent("on order");
    expect(screen.getByRole("link", { name: "PO/2026/0001" })).toHaveAttribute(
      "href",
      "/purchase-orders/po-1",
    );
    expect(screen.queryByTestId("maker-recipe-order-shortage")).toBeNull();
  });
});
