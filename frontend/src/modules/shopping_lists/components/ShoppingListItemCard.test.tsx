import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/test/utils";
import { ShoppingListItemCard } from "./ShoppingListItemCard";
import type { ShoppingListItem } from "@/modules/shopping_lists/types/shopping";
import { withLanguage } from "@/test/mocks/i18n";

const unitsRead = vi.hoisted(() => ({ failed: false }));
vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: unitsRead.failed
      ? undefined
      : [
          { id: "uom-pcs", name: "Piece", symbol: "pcs" },
          { id: "uom-g", name: "Gram", symbol: "g" },
        ],
    isError: unitsRead.failed,
  }),
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useOrganization: () => ({ data: { currency: "PLN" } }),
}));

const noop = vi.fn();

const baseItem: ShoppingListItem = {
  id: "li-1",
  shopping_list_id: "list-1",
  item_id: null,
  category_id: null,
  template_id: null,
  name: "Ciecierzyca w puszce",
  quantity: "800",
  uom_id: "uom-g",
  uom: { id: "uom-g", name: "Gram", symbol: "g", rounding: "1" },
  notes: null,
  estimated_price: null,
  priority: 0,
  source: "meal_plan",
  is_purchased: false,
  purchased_at: null,
  purchased_by: null,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
};

const renderCard = (item: ShoppingListItem) =>
  render(<ShoppingListItemCard item={item} onToggle={noop} onDelete={noop} />);

describe("ShoppingListItemCard — the service-composed note", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    unitsRead.failed = false;
  });

  it("falls back to the stored note instead of printing quantities without units when the units failed", () => {
    unitsRead.failed = true;
    renderCard({
      ...baseItem,
      notes: "Check stock: 7 pcs in stock, recipe needs 800 g",
      note_data: {
        check_stock: {
          available_qty: 7,
          available_uom_id: "uom-pcs",
          required_qty: 800,
          required_uom_id: "uom-g",
        },
      },
    });

    expect(
      screen.getByText("Check stock: 7 pcs in stock, recipe needs 800 g"),
    ).toBeInTheDocument();
  });

  it("re-composes the check-stock note in the reader's language, units translated", async () => {
    await withLanguage("pl", () => {
      renderCard({
        ...baseItem,
        note_data: {
          check_stock: {
            available_qty: 7,
            available_uom_id: "uom-pcs",
            required_qty: 800,
            required_uom_id: "uom-g",
          },
        },
      });

      // "pcs" of the generation run must not leak into the Polish sentence.
      expect(
        screen.getByText(
          "Sprawdź stan: 7 szt. na stanie, przepis wymaga 800 g",
        ),
      ).toBeInTheDocument();
    });
  });

  it("composes every note part in English with the same structured data", async () => {
    renderCard({
      ...baseItem,
      note_data: {
        needed_by: "2026-09-01",
        check_stock: {
          available_qty: 7,
          available_uom_id: "uom-pcs",
          required_qty: 800,
          required_uom_id: "uom-g",
        },
        matched_by_name: "Chickpeas in a can",
      },
    });

    expect(
      screen.getByText(/Check stock: 7 pcs\. in stock/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Needed by:/)).toBeInTheDocument();
    expect(
      screen.getByText(/Matched by name to "Chickpeas in a can"/),
    ).toBeInTheDocument();
  });

  it("names the purchase order a line went to in the reader's language, beside the line's own note", async () => {
    await withLanguage("pl", () => {
      renderCard({
        ...baseItem,
        source: "manual",
        notes: "niebieski karton",
        note_data: { converted_to_po: "PO/2026/001" },
      });

      expect(
        screen.getByText("niebieski karton · Na zamówieniu PO/2026/001"),
      ).toBeInTheDocument();
    });
  });

  it("adds the purchase order to the composed parts, not to their fallback", () => {
    renderCard({
      ...baseItem,
      notes: "Needed by: 9/1/2026",
      note_data: { needed_by: "2026-09-01", converted_to_po: "PO/2026/001" },
    });

    expect(
      screen.getByText(/^Needed by: .* · On purchase order PO\/2026\/001$/),
    ).toBeInTheDocument();
  });

  // "For recipe: Chicken fried rice" was written in the language of whoever
  // pressed the button and read English in a Polish kitchen.
  it("names the recipe a line came from in the reader's language", async () => {
    await withLanguage("pl", () => {
      renderCard({
        ...baseItem,
        source: "recipe",
        notes: "For recipe: Chicken fried rice",
        note_data: { for_recipe: "Chicken fried rice" },
      });

      expect(
        screen.getByText("Do przepisu: Chicken fried rice"),
      ).toBeInTheDocument();
      expect(screen.queryByText(/For recipe/)).not.toBeInTheDocument();
    });
  });

  it("re-tells a recipe note stored before the recipe travelled as data", async () => {
    await withLanguage("de", () => {
      renderCard({
        ...baseItem,
        source: "recipe",
        notes: "For recipe: Chicken fried rice",
      });

      expect(
        screen.getByText("Für Rezept: Chicken fried rice"),
      ).toBeInTheDocument();
    });
  });

  it("prints the composed fallback when the line carries no structured data", () => {
    renderCard({ ...baseItem, notes: "Best from local store" });

    expect(screen.getByText("Best from local store")).toBeInTheDocument();
  });
});

describe("ShoppingListItemCard — the unit the line actually has", () => {
  it("says nothing about a unit the line does not carry", () => {
    // An ingredient a recipe records without a measure reaches the list with
    // uom_id null. The card printed "pcs" for it, putting back the unit the
    // service had deliberately stopped borrowing from the product.
    renderCard({ ...baseItem, quantity: "2", uom_id: null, uom: null });

    expect(screen.getByText(/^2\s+—$/)).toBeInTheDocument();
    expect(screen.queryByText(/\bpcs\b/)).not.toBeInTheDocument();
  });

  it("shows the places the unit allows, not the column's padding", () => {
    renderCard({
      ...baseItem,
      quantity: "1",
      uom_id: "uom-pcs",
      uom: {
        id: "uom-pcs",
        name: "Piece",
        symbol: "pcs",
        rounding: "1.000000",
      },
    });

    expect(screen.getByText(/^1\s+pcs\.$/)).toBeInTheDocument();
  });
});

describe("ShoppingListItemCard — row actions name their row", () => {
  // Every line had a "Toggle purchased" and a "Delete" with nothing telling
  // them apart: a screen reader listing the buttons heard the same two
  // names once per line.
  it("names the line in its tick and its delete button", () => {
    renderCard(baseItem);

    expect(
      screen.getByRole("button", {
        name: "Toggle purchased: Ciecierzyca w puszce",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete Ciecierzyca w puszce" }),
    ).toBeInTheDocument();
  });
});
