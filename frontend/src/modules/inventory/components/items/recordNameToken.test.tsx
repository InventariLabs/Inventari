/**
 * One rank for the name of a record, on every list in the product.
 *
 * The name of a record is the most repeated element in the interface and the
 * only thing in a row worth clicking, and six main lists gave it four
 * different ranks: 14/500 in the product and equipment tables, 14/600 in
 * recipes, 16/600 in maker, and 20/600 on the shopping lists — where it was
 * byte for byte the page-title token from UI_GUIDELINES §11.2, so the page
 * had nine headings of equal weight and no way in.
 *
 * The classes are asserted rather than the computed size because jsdom
 * applies no stylesheet; the rendered result is measured on the running app.
 */
import { render, screen } from "@/test/utils";
import { describe, expect, it, vi } from "vitest";
import type { Item } from "@/types";
import { ShoppingListCard } from "@/modules/shopping_lists/components/ShoppingListCard";
import type { ShoppingList } from "@/modules/shopping_lists/types/shopping";

import ItemTable from "./ItemTable";

/** `text-sm font-semibold` — 14px at weight 600. */
const RECORD_NAME = /text-sm[^"]*font-semibold|font-semibold[^"]*text-sm/;

const makeItem = (id: string, overrides: Partial<Item> = {}): Item =>
  ({
    id,
    name: `Item ${id}`,
    quantity: 1,
    organization_id: "org-1",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }) as Item;

const baseProps = {
  storages: [],
  categories: [],
  enabledModules: [],
  onItemClick: vi.fn(),
  onConsume: vi.fn(),
  onAddOne: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onSetThreshold: vi.fn(),
  consumingId: null,
  selectedIds: [],
  onToggleSelect: vi.fn(),
  onSelectAll: vi.fn(),
};

describe("the record name carries one token", () => {
  it("gives the product row the record-name rank", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const name = screen.getByTitle("Item 1");
    expect(name.className).toMatch(RECORD_NAME);
  });

  it("keeps it below the page title, which no list row may match", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    // §11.2: `text-xl font-semibold` belongs to the page's `h1` alone.
    const name = screen.getByTitle("Item 1");
    expect(name.className).not.toContain("text-xl");
    expect(name.className).not.toContain("text-lg");
  });

  it("gives a card the same rank as a row", () => {
    const list: ShoppingList = {
      id: "list-1",
      organization_id: "org-1",
      name: "Weekly Shopping",
      status: "active",
      created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    render(
      <ShoppingListCard
        list={list}
        stats={{ total: 3, purchased: 1, names: ["Flour"] }}
        editingName={null}
        newName=""
        to="/shopping-lists/list-1"
        onSetNewName={vi.fn()}
        onStartEditName={vi.fn()}
        onSaveName={vi.fn()}
        onDeleteRequest={vi.fn()}
      />,
    );

    // The token guards the record name, not the table: a card that drifted
    // back to `text-xl` would be the page title's twin.
    const name = screen.getByText("Weekly Shopping").closest("h3");
    expect(name?.className).toMatch(RECORD_NAME);
    expect(name?.className).not.toContain("text-xl");
    expect(name?.className).not.toContain("text-lg");
  });
});
