import { render, screen, waitFor } from "@/test/utils";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import userEvent from "@testing-library/user-event";
import { withLanguage } from "@/test/mocks/i18n";
import { itemsApi } from "@/lib/api/items";
import QuickActionSheet from "./QuickActionSheet";
import type { Item } from "@/types";
import { formatDate } from "@/utils/formatters";

// Every action in the sheet changes the record, so the sheet is empty for an
// account that may not — which is a different screen than these tests mean.
beforeEach(() => {
  signInWith(["items:read", "items:write"]);
});
afterEach(() => signOut());

vi.mock("../lib/api", () => ({
  itemsApi: {
    consume: vi
      .fn()
      .mockResolvedValue({ id: "item-1", quantity: 1, is_deleted: false }),
    discard: vi.fn().mockResolvedValue({}),
  },
}));

// The sheet consumes through this module, which the relative mock above never
// sees. Everything else stays real; only consume is observable here.
vi.mock("@/lib/api/items", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/items")>();
  return {
    ...actual,
    itemsApi: { ...actual.itemsApi, consume: vi.fn() },
  };
});

describe("QuickActionSheet", () => {
  const mockItem = {
    id: "item-1",
    location_id: "storage-1",
    category_id: null,
    name: "Fresh Milk",
    brand: "Mlekovita",
    description: null,
    weight: null,
    uom_id: null,
    uom: null,
    quantity: "2",
    added_date: new Date().toISOString(),
    expiry_date: "2026-12-31",
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    is_deleted: false,
    deleted_at: null,
    deletion_reason: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    barcode: undefined,
    serial_number: null,
  };

  it("should render item details and actions", () => {
    render(<QuickActionSheet item={mockItem} onClose={() => {}} />);

    expect(screen.getByText(/Fresh Milk/i)).toBeInTheDocument();
    expect(screen.getByText(/Mlekovita/i)).toBeInTheDocument();
    // No unit on the item means no unit shown — the UI does not invent one.
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows the opened package's effective expiry instead of the batch date", () => {
    render(
      <QuickActionSheet
        item={{ ...mockItem, effective_expiry_date: "2020-01-02" }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(formatDate("2020-01-02"))).toBeInTheDocument();
    expect(
      screen.queryByText(formatDate("2026-12-31")),
    ).not.toBeInTheDocument();
  });

  /**
   * The list's sheet offers an asset the same switched actions as the product
   * page, so it owes the same sentence about why they sound different.
   */
  it("explains an asset's vocabulary above its actions", () => {
    render(
      <QuickActionSheet
        item={
          {
            ...mockItem,
            category: { context_tag: "equipment" },
          } as unknown as Item
        }
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/checked in and disposed of/i)).toBeInTheDocument();
  });

  it("adds no such sentence to a product", () => {
    render(<QuickActionSheet item={mockItem} onClose={() => {}} />);

    expect(screen.queryByText(/checked in and disposed of/i)).toBeNull();
  });

  /**
   * A product without a brand fell back to the hard-coded English "No brand"
   * on the sheet of every language. The fallback is a catalogue entry now,
   * so the sheet says it in the reader's words.
   */
  it("names a missing brand in the reader's language", async () => {
    await withLanguage("pl", () => {
      render(
        <QuickActionSheet
          item={{ ...mockItem, brand: null }}
          onClose={() => {}}
        />,
      );

      expect(screen.getByText("Brak marki")).toBeInTheDocument();
      expect(screen.queryByText("No brand")).toBeNull();
    });
  });

  /**
   * The sheet printed the canonical symbol while the list one layer down
   * printed the translated one: "6 pcs" above a row reading "6 SZT.".
   */
  it("writes the unit the way the rest of the interface writes it", async () => {
    await withLanguage("pl", () => {
      render(
        <QuickActionSheet
          item={{
            ...mockItem,
            quantity: "6",
            uom: {
              id: "uom-1",
              symbol: "pcs",
              name: "Pieces",
              category_name: "COUNT",
              rounding: "1",
            },
          }}
          onClose={() => {}}
        />,
      );

      expect(screen.getByText(/6\s*szt\./i)).toBeInTheDocument();
      expect(screen.queryByText(/6\s*pcs/)).toBeNull();
    });
  });

  /**
   * "Add to shopping list" came from two places at once: the module's slot
   * contribution and a copy Core kept of the same action.
   */
  it("offers adding to a shopping list once, from the module that owns it", () => {
    render(<QuickActionSheet item={mockItem} onClose={() => {}} />);

    expect(
      screen.queryAllByRole("button", { name: /shopping list/i }).length,
    ).toBeLessThanOrEqual(1);
  });

  it("asks the page to move the item rather than opening the edit form", async () => {
    const onMove = vi.fn();
    const onViewDetails = vi.fn();
    render(
      <QuickActionSheet
        item={mockItem}
        onClose={() => {}}
        onMove={onMove}
        onViewDetails={onViewDetails}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^move$/i }));

    expect(onMove).toHaveBeenCalled();
    expect(onViewDetails).not.toHaveBeenCalled();
  });

  /**
   * "Check out" and "Decommission" both called onViewDetails — a button named
   * after a movement that opened the edit form instead of recording it.
   */
  it("does not offer equipment movements it cannot perform", () => {
    render(
      <QuickActionSheet
        item={{
          ...mockItem,
          category: {
            id: "c1",
            name: "Laptops",
            context_tag: "equipment",
          } as unknown as Item["category"],
        }}
        onClose={() => {}}
      />,
    );

    expect(screen.queryByRole("button", { name: /check out/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /decommission/i })).toBeNull();
  });

  /**
   * "Remove 1 unit" on a record measured in kilograms took the whole record:
   * a reader who asked for one kilogram lost the two they had. The sheet and
   * the product page share the hook this asserts through. Reverting the fix
   * makes the expectation below read 2 and fail.
   */
  it("takes one unit when the action says Remove 1 unit", async () => {
    const kgUom = {
      id: "uom-kg",
      symbol: "kg",
      name: "Kilograms",
      category_name: "WEIGHT",
      rounding: "1",
    };
    vi.mocked(itemsApi.consume).mockResolvedValue({
      ...mockItem,
      quantity: "1",
      uom: kgUom,
    } as Item);

    render(
      <QuickActionSheet
        item={{ ...mockItem, quantity: "2", uom: kgUom }}
        onClose={() => {}}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Remove 1 unit" }),
    );

    await waitFor(() => {
      expect(itemsApi.consume).toHaveBeenCalledWith(
        "item-1",
        1,
        "USED",
        undefined,
      );
    });
  });

  it("hides Edit from a reader, keeping the reads", () => {
    // The grid is gated by the hook behind it, but this button was written
    // beside the grid without a question: a reader's shortcut opened the
    // full edit form and met the 403 at Save.
    signInWith(["items:read"]);
    render(<QuickActionSheet item={mockItem} onClose={() => {}} />);

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.getByText("Product details")).toBeInTheDocument();
  });
});
