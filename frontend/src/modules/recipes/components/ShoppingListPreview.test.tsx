import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ShoppingListPreview } from "./ShoppingListPreview";
import en from "@/modules/recipes/i18n/en.json";
import type { ShoppingListGenerationResult } from "@/modules/recipes/types/mealplans";
import commonEn from "@/i18n/locales/en/common.json";

const modulesMock = vi.hoisted(() => ({ shoppingListsEnabled: true }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isModuleEnabled: (name: string) =>
      name === "shopping_lists" && modulesMock.shoppingListsEnabled,
  }),
}));

const t = (key: string, opts?: Record<string, unknown>) => {
  // The component asks the unit catalogue by its namespace, the way every
  // screen does; a stub that only knows its own catalogue answered with the
  // key and the chip read "common:units.ml".
  if (key.startsWith("common:units.")) {
    const symbol = key.slice("common:units.".length);
    const words = commonEn.units as unknown as Record<string, string>;
    return String(words[symbol] ?? symbol);
  }
  const path = key.replace("recipes:", "").split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = en;
  for (const part of path) value = value?.[part];
  if (typeof value !== "string") return key;
  return value.replace(/\{\{\w+\}\}/g, (m) =>
    String(opts?.[m.slice(2, -2)] ?? m),
  );
};

const result: ShoppingListGenerationResult = {
  shopping_list_id: "list-1",
  total_ingredients: 7,
  available_count: 2,
  to_buy_count: 5,
  items: [
    {
      name: "Flour",
      quantity: "500",
      uom_symbol: "g",
      needed_by: null,
      quantities_comparable: true,
      matched_approximately: false,
    },
    {
      name: "Coconut milk",
      quantity: "200",
      uom_symbol: "ml",
      needed_by: null,
      quantities_comparable: true,
      matched_approximately: false,
    },
  ],
};

const renderPreview = (
  props: Partial<React.ComponentProps<typeof ShoppingListPreview>> = {},
) =>
  render(
    <MemoryRouter>
      <ShoppingListPreview
        planId="p1"
        hasMeals
        isGenerating={false}
        onGenerate={vi.fn()}
        t={t}
        {...props}
      />
    </MemoryRouter>,
  );

describe("ShoppingListPreview", () => {
  it("shows the counters right after generating, even though the plan now has a list id", () => {
    renderPreview({ generationResult: result, existingListId: "list-1" });

    expect(screen.getByText("Shopping list ready")).toBeInTheDocument();
    expect(
      screen.getByText("7 ingredients · 2 in pantry · 5 to buy"),
    ).toBeInTheDocument();
  });

  it("carries the unit symbol into the summary chips, like the list itself", () => {
    renderPreview({ generationResult: result });

    expect(screen.getByText(/Flour \(500 g\)/)).toBeInTheDocument();
    expect(screen.getByText(/Coconut milk \(200 ml\)/)).toBeInTheDocument();
  });

  it("keeps two units of one product apart, in two chips and without a key clash", () => {
    // The backend stopped adding grams to pieces, so one product now leaves
    // two lines with the same name — and the name was this list's key.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderPreview({
      generationResult: {
        ...result,
        items: [
          {
            name: "Flour",
            quantity: "500",
            uom_symbol: "g",
            needed_by: null,
            quantities_comparable: true,
            matched_approximately: false,
          },
          {
            name: "Flour",
            quantity: "2",
            uom_symbol: "pcs",
            needed_by: null,
            quantities_comparable: true,
            matched_approximately: false,
          },
        ],
      },
    });

    expect(screen.getByText(/Flour \(500 g\)/)).toBeInTheDocument();
    expect(screen.getByText(/Flour \(2 pcs\.\)/)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("takes a returning visitor to the existing list in one click", () => {
    renderPreview({ existingListId: "list-9" });

    const link = screen.getByRole("link", { name: /view shopping list/i });
    expect(link).toHaveAttribute("href", "/shopping-lists/list-9");
    expect(screen.queryByText("Shopping list ready")).not.toBeInTheDocument();
  });

  // The line used to stand under every generated list, true or not; the plan
  // now says whether a meal was planned after the list was made.
  it("says meals are missing from the list only when some are", () => {
    const hint = "Meals added after the list was generated are not on it yet.";
    const { unmount } = renderPreview({ existingListId: "list-9" });
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    unmount();

    renderPreview({ existingListId: "list-9", mealsAddedSinceList: true });
    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  // The result of this session's run described the list it had just made;
  // a meal planned after it is not on that list, and the summary kept
  // saying "ready" with no hint and no way to update.
  it("drops this run's summary once a meal is planned after it", () => {
    renderPreview({
      existingListId: "list-1",
      generationResult: result,
      mealsAddedSinceList: true,
    });

    expect(screen.queryByText("Shopping list ready")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Meals added after the list was generated are not on it yet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /update list/i }),
    ).toBeInTheDocument();
  });

  it("offers generation when there is neither a result nor a list", () => {
    renderPreview();

    expect(
      screen.getByRole("button", { name: /generate shopping list/i }),
    ).toBeEnabled();
  });

  it("disables Generate Shopping List with a tooltip when the plan has no meals", () => {
    renderPreview({ hasMeals: false });

    const button = screen.getByRole("button", {
      name: /generate shopping list/i,
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Add meals first");
  });

  it("hides the whole shopping section when the shopping_lists module is disabled", () => {
    modulesMock.shoppingListsEnabled = false;
    const { container } = renderPreview();

    expect(container).toBeEmptyDOMElement();

    modulesMock.shoppingListsEnabled = true;
  });
});
