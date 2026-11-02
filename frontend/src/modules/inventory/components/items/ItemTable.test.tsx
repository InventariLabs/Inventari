import { render, screen, waitFor, within } from "@/test/utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import type { Item } from "@/types";
import { moduleRegistry } from "@/lib/moduleRegistry";
import ItemTable, { ACTION_BUTTONS } from "./ItemTable";

/**
 * A module column that no row on the page fills — "Formula" on a list
 * of products with no bill of materials — was rendered as a column of blanks,
 * taking width from the columns that had something in them.
 */
const makeItem = (id: string, overrides: Partial<Item> = {}): Item =>
  ({
    id,
    name: `Item ${id}`,
    quantity: 1,
    organization_id: "org-1",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_deleted: false,
    ...overrides,
  }) as Item;

const baseProps = {
  storages: [],
  categories: [],
  enabledModules: ["maker"],
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

describe("ItemTable — module column contributors", () => {
  beforeEach(() => {
    vi.spyOn(moduleRegistry, "getColumnContributors").mockReturnValue([
      {
        key: "formula",
        label: "Formula",
        requiredModule: "maker",
        position: "after-name",
        width: "90px",
        hasValue: (item) => Boolean(item.template_id),
        render: () => null,
      },
    ]);
  });

  it("drops a column no row on the page fills", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1"), makeItem("2")]} />);

    expect(screen.queryByText("Formula")).toBeNull();
  });

  it("keeps the column as soon as one row fills it", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1"), makeItem("2", { template_id: "tpl-1" })]}
      />,
    );

    expect(screen.getByText("Formula")).toBeInTheDocument();
  });

  it("drops a column whose own probe says the page has nothing for it", async () => {
    // `hasValue` can only read the row. "Does this product have a formula?"
    // lives behind a query, and every product carries a template, so a
    // template-shaped predicate answered yes for a column of blanks.
    vi.spyOn(moduleRegistry, "getColumnContributors").mockReturnValue([
      {
        key: "formula",
        label: "Formula",
        requiredModule: "maker",
        position: "after-name",
        useHasValues: () => false,
        render: () => null,
      },
    ]);

    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { template_id: "tpl-1" })]}
      />,
    );

    await waitFor(() => expect(screen.queryByText("Formula")).toBeNull());
  });

  it("keeps the column once its probe finds something", async () => {
    vi.spyOn(moduleRegistry, "getColumnContributors").mockReturnValue([
      {
        key: "formula",
        label: "Formula",
        requiredModule: "maker",
        position: "after-name",
        useHasValues: () => true,
        render: () => null,
      },
    ]);

    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { template_id: "tpl-1" })]}
      />,
    );

    expect(await screen.findByText("Formula")).toBeInTheDocument();
  });

  it("renders no cell of a new page before its probe has answered", async () => {
    // A cell may ask its own question on mount. Carrying "yes" over from the
    // previous page mounted the next page's cells before the page's one
    // batched answer was in, and each asked for itself.
    const rendered: string[] = [];
    vi.spyOn(moduleRegistry, "getColumnContributors").mockReturnValue([
      {
        key: "formula",
        label: "Formula",
        requiredModule: "maker",
        position: "after-name",
        // Page one answers at once; page two is still waiting.
        useHasValues: (items) => (items[0].id === "1" ? true : undefined),
        render: (item) => {
          rendered.push(item.id);
          return null;
        },
      },
    ]);

    const { rerender } = render(
      <ItemTable {...baseProps} items={[makeItem("1")]} />,
    );
    expect(await screen.findByText("Formula")).toBeInTheDocument();

    rendered.length = 0;
    rerender(<ItemTable {...baseProps} items={[makeItem("2")]} />);

    expect(screen.queryByText("Formula")).toBeNull();
    expect(rendered).not.toContain("2");
  });

  it("keeps a column that does not say whether it has data", () => {
    vi.spyOn(moduleRegistry, "getColumnContributors").mockReturnValue([
      {
        key: "formula",
        label: "Formula",
        requiredModule: "maker",
        position: "after-name",
        render: () => null,
      },
    ]);

    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    expect(screen.getByText("Formula")).toBeInTheDocument();
  });
});

describe("ItemTable — table semantics", () => {
  beforeEach(() => {
    vi.spyOn(moduleRegistry, "getColumnContributors").mockReturnValue([]);
  });

  it("renders a real table with column headers", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(
      expect.arrayContaining(["Product", "Location", "Quantity", "Actions"]),
    );
  });

  it("puts each item in its own row", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1"), makeItem("2")]} />);

    // One header row plus one row per item.
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("marks the sorted column with aria-sort", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1")]}
        sortBy="name"
        sortOrder="asc"
      />,
    );

    expect(
      screen.getByRole("columnheader", { name: "Product" }),
    ).toHaveAttribute("aria-sort", "ascending");
    expect(
      screen.getByRole("columnheader", { name: "Quantity" }),
    ).not.toHaveAttribute("aria-sort");
  });

  it("follows the sort onto another column and direction", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1")]}
        sortBy="quantity"
        sortOrder="desc"
      />,
    );

    expect(
      screen.getByRole("columnheader", { name: "Quantity" }),
    ).toHaveAttribute("aria-sort", "descending");
  });

  it("leaves every column unsorted when the list is ordered by something with no column", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1")]}
        sortBy="created_at"
        sortOrder="desc"
      />,
    );

    for (const header of screen.getAllByRole("columnheader")) {
      expect(header).not.toHaveAttribute("aria-sort");
    }
  });
});

/**
 * the desktop row's product block was a `<div onClick>` — mouse-only.
 * It is a real button now, named after the product it opens.
 */
describe("ItemTable — row as a button", () => {
  it("exposes the product name as a button and fires once on Enter", async () => {
    const user = userEvent.setup();
    const onItemClick = vi.fn();
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1")]}
        onItemClick={onItemClick}
      />,
    );

    const target = screen.getByRole("button", { name: /^Item 1/ });
    target.focus();
    await user.keyboard("{Enter}");

    expect(onItemClick).toHaveBeenCalledTimes(1);
    expect(onItemClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "1" }),
    );
  });
});

/**
 * the row button's `aria-label` replaced the name computed from its
 * content, so brand, code, SKU and category were announced by nothing.
 */
describe("ItemTable — the row name carries its metadata", () => {
  it("names the row after everything inside it, not just the product", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[
          makeItem("1", {
            template: { sku: "SKU-9001" } as Item["template"],
            brand: "Acme",
          }),
        ]}
      />,
    );

    const row = screen.getByRole("button", { name: /^Item 1/ });
    expect(row).toHaveAccessibleName(/Acme/);
    expect(row).toHaveAccessibleName(/SKU-9001/);
  });

  it("keeps the thumbnail out of the name instead of saying it twice", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { image_url: "https://example.test/i.png" })]}
      />,
    );

    const row = screen.getByRole("button", { name: /^Item 1/ });
    expect(row.querySelector("img")).toHaveAttribute("alt", "");
    expect(row.textContent).toContain("Item 1");
  });
});

/**
 * the desktop row separated "below threshold" from "has a threshold,
 * is fine" by an amber tint against a dashed amber border — one state for
 * anyone who does not split those two hues. It says the word now, like the
 * mobile card since.
 */
describe("ItemTable — low stock speaks in a word", () => {
  it("shows the warning badge below the threshold", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { quantity: "1", min_quantity: 2 })]}
      />,
    );

    expect(screen.getByText("Low")).toBeInTheDocument();
  });

  it("carries no signal when the threshold is set but met", () => {
    const { container } = render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { quantity: "10", min_quantity: 2 })]}
      />,
    );

    expect(screen.queryByText("Low")).toBeNull();
    expect(container.querySelector('[class*="border-dashed"]')).toBeNull();
    expect(container.querySelector('[class*="amber"]')).toBeNull();
  });

  it("carries no signal without a threshold", () => {
    const { container } = render(
      <ItemTable {...baseProps} items={[makeItem("1", { quantity: "1" })]} />,
    );

    expect(screen.queryByText("Low")).toBeNull();
    expect(container.querySelector('[class*="amber"]')).toBeNull();
  });

  it("keeps the badge out of the threshold button, which stays one control", async () => {
    const user = userEvent.setup();
    const onSetThreshold = vi.fn();
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { quantity: "1", min_quantity: 2 })]}
        onSetThreshold={onSetThreshold}
      />,
    );

    const quantityButton = screen.getByTitle("Set stock alert");
    expect(quantityButton.textContent).not.toMatch(/low/i);

    await user.click(quantityButton);
    expect(onSetThreshold).toHaveBeenCalledTimes(1);
  });
});

/**
 * the row button drew Chrome's default outline instead of the
 * app's ring, and the quantity button announced itself as "1 PCS." — a `title`
 * names nothing that already has content of its own.
 */
describe("ItemTable — focus ring and the quantity button's name", () => {
  it("names the quantity button after what it does", async () => {
    const user = userEvent.setup();
    const onSetThreshold = vi.fn();
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { quantity: "4" })]}
        onSetThreshold={onSetThreshold}
      />,
    );

    const quantityButton = screen.getByRole("button", {
      name: /set stock alert/i,
    });
    expect(quantityButton).toHaveAccessibleName(/Item 1/);
    expect(quantityButton).toHaveAccessibleName(/4/);

    await user.click(quantityButton);
    expect(onSetThreshold).toHaveBeenCalledTimes(1);
  });

  /**
   * axe reads the shown parts as one run of text — "4pcs." — and the
   * `aria-label` spelled them "4 pcs." in the middle of a sentence, so the
   * name did not contain what the button shows and a voice user saying it
   * reached nothing (WCAG 2.5.3, `label-content-name-mismatch`).
   */
  it("starts its name with the quantity and unit it shows", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[
          makeItem("1", {
            quantity: "4",
            uom: { symbol: "kg" } as Item["uom"],
          }),
        ]}
      />,
    );

    // The shown parts joined as axe joins inline elements: without a space.
    const button = screen.getByTitle("Set stock alert");
    const shown = Array.from(button.children)
      .filter((el) => !el.classList.contains("sr-only"))
      .map((el) => el.textContent)
      .join("");
    expect(shown).toBe("4kg");
    expect(button).toHaveAccessibleName(/^4kg\b.*set stock alert for item 1/i);
    expect(button).not.toHaveAttribute("aria-label");
  });

  it("shows a partly used pack as the fraction left, not a whole pack", () => {
    // Rice cooked down by 100 g is 0.9 pack everywhere else in the app.
    render(
      <ItemTable
        {...baseProps}
        items={[
          makeItem("1", {
            quantity: "0.900",
            uom: { symbol: "pack", rounding: "1.000000" } as Item["uom"],
          }),
        ]}
      />,
    );

    const button = screen.getByTitle("Set stock alert");
    expect(button.children[0]).toHaveTextContent(/^0\.9$/);
  });

  it("draws the app's focus ring on the row button", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const row = screen.getByRole("button", { name: /^Item 1/ });
    expect(row.className).toContain("focus-visible:ring-2");
    expect(row.className).toContain("focus-visible:ring-ring");
    expect(row.className).toContain("focus-visible:outline-none");
  });
});

/**
 * row actions used to sit at opacity-40 until hover — reading as
 * disabled, failing AA, and never appearing on touch. They rest on
 * text-on-muted now, and Delete is separated and marked danger at rest.
 */
describe("ItemTable — always-visible row actions", () => {
  it("never hides the actions behind hover opacity", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const deleteButton = screen.getByRole("button", { name: /^delete$/i });
    const container = deleteButton.parentElement as HTMLElement;
    expect(container.className).not.toMatch(/opacity-40/);
    expect(container.className).not.toMatch(/group-hover/);
  });

  it("separates Delete and marks it danger at rest", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const deleteButton = screen.getByRole("button", { name: /^delete$/i });
    expect(deleteButton.className).toMatch(/text-on-danger/);

    const divider = deleteButton.previousElementSibling;
    expect(divider).not.toBeNull();
    expect(divider).toHaveAttribute("aria-hidden", "true");
  });

  it("links each row to its product page, for a reader as well as a writer", () => {
    const { rerender } = render(
      <ItemTable {...baseProps} items={[makeItem("1")]} />,
    );
    expect(
      screen.getByRole("link", { name: /^product details$/i }),
    ).toHaveAttribute("href", "/inventory/items/1");

    rerender(
      <ItemTable {...baseProps} canWrite={false} items={[makeItem("1")]} />,
    );
    expect(
      screen.getByRole("link", { name: /^product details$/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit$/i })).toBeNull();
  });

  it("hides Delete from a writer without items:delete, and keeps the rest", () => {
    render(
      <ItemTable {...baseProps} canDelete={false} items={[makeItem("1")]} />,
    );

    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).toBeNull();
  });
});

/**
 * Six rows out of 584 records is a viewer, not a list. The row had grown a
 * `py-4` cell around a 48px thumbnail; UI_GUIDELINES §14.1a fixes the budget,
 * and the hairline redesign compacts the row further to `py-2`.
 */
describe("ItemTable — row density", () => {
  it("keeps the desktop row inside its height budget", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const cells = screen.getByTestId("item-row").querySelectorAll("td");
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.className).toContain("py-2");
      expect(cell.className).not.toContain("py-4");
    }
  });

  it("shows the serial number that tells one row from the next", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[
          makeItem("1", { name: "Rack 42U", serial_number: "SN-483699" }),
          makeItem("2", { name: "Rack 42U", serial_number: "SN-891149" }),
        ]}
      />,
    );

    expect(screen.getByText("SN-483699")).toBeInTheDocument();
    expect(screen.getByText("SN-891149")).toBeInTheDocument();
  });
});

describe("ItemTable — symmetric quantity actions", () => {
  it("offers +1 beside the button that removes 1", async () => {
    const onAddOne = vi.fn();
    render(
      <ItemTable {...baseProps} items={[makeItem("1")]} onAddOne={onAddOne} />,
    );

    expect(
      screen.getByRole("button", { name: "Remove 1 unit" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add 1 unit" }));

    expect(onAddOne).toHaveBeenCalledWith("1");
  });
});

/**
 * The storage link was an `<a>` with a working `href` that still did nothing
 * when clicked. Storage paths are long, so the inline link wrapped onto two
 * lines; the two line boxes left an interline gap down the middle of its
 * bounding box, and the centre of that box — where a reader aims, and where
 * `elementFromPoint` lands — resolved to the `<td>` instead of the link.
 * One line is one box with no hole in it. jsdom has no layout, so the
 * regression is guarded at its cause: the classes that forbid the wrap.
 */
describe("ItemTable — the storage cell is one click target", () => {
  const storages = [
    { id: "site-1", name: "Main Warehouse", parent_id: null },
    { id: "bay-3", name: "Bay 3", parent_id: "site-1" },
  ] as never;

  const renderWithStorage = () =>
    render(
      <ItemTable
        {...baseProps}
        storages={storages}
        items={[makeItem("1", { location_id: "bay-3" })]}
      />,
    );

  it("keeps the link a single box, and cuts only the road to the leaf", () => {
    renderWithStorage();

    const link = screen.getByRole("link", { name: /Main Warehouse/ });
    expect(link.className).toContain("block");
    expect(screen.getByTestId("item-location-parents").className).toContain(
      "truncate",
    );
  });

  it("prints the leaf of a long path uncut, whatever the cell's width", () => {
    // Twelve records of one product on twelve shelves differ only in the
    // last segment. Cutting the path at its end printed twelve identical rows.
    render(
      <ItemTable
        {...baseProps}
        storages={
          [
            { id: "site", name: "Pantry Building", parent_id: null },
            { id: "zone", name: "Dry Goods", parent_id: "site" },
            { id: "shelf", name: "Shelf A - Bottom", parent_id: "zone" },
          ] as never
        }
        items={[makeItem("1", { location_id: "shelf" })]}
      />,
    );

    const link = screen.getByRole("link", {
      name: "Pantry Building → Dry Goods → Shelf A - Bottom",
    });
    const leaf = screen.getByText("Shelf A - Bottom");
    expect(link).toContainElement(leaf);
    expect(leaf.className).not.toContain("truncate");
    expect(
      leaf.compareDocumentPosition(
        screen.getByText("Pantry Building → Dry Goods"),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("Pantry Building → Dry Goods").className).toContain(
      "truncate",
    );
  });

  it("reads as a link before anyone hovers it", () => {
    renderWithStorage();

    // `hover:underline` alone is no affordance on a screen with no pointer,
    // and no affordance at all for a reader who never hovers to find out.
    const link = screen.getByRole("link", { name: /Main Warehouse/ });
    expect(link.className).toMatch(/(^|\s)underline(\s|$)/);
  });

  it("opens the storage, not a filter of the list it is already on", () => {
    renderWithStorage();

    // Narrowing this list to that storage made the link dead exactly where it
    // is most likely to be pressed: on the narrowed list, where every row
    // names the same place and the destination is the page already shown.
    const link = screen.getByRole("link", { name: /Main Warehouse/ });
    expect(link).toHaveAttribute("href", "/inventory/locations/bay-3");
  });

  it("names the whole path, not just the leaf", () => {
    renderWithStorage();

    expect(
      screen.getByRole("link", { name: "Main Warehouse → Bay 3" }),
    ).toBeInTheDocument();
  });

  /**
   * A used-up record is filed under the virtual Consumed place. The row's
   * Location column must say that name — not "Unknown" — which the naming
   * list reaching virtual locations made true; this pins it for the used-up
   * view the row appears in.
   */
  describe("ItemTable — the used-up row names the virtual place", () => {
    it("shows Consumed (Virtual), never Unknown, for a record filed there", () => {
      render(
        <ItemTable
          {...baseProps}
          storages={
            [
              { id: "site-1", name: "Main Warehouse", parent_id: null },
              {
                id: "consumed-1",
                name: "Consumed (Virtual)",
                parent_id: null,
                usage: "customer",
              },
            ] as never
          }
          items={[makeItem("1", { location_id: "consumed-1" })]}
        />,
      );

      expect(
        screen.getByRole("link", { name: "Consumed (Virtual)" }),
      ).toBeInTheDocument();
      expect(screen.queryByText("Unknown")).not.toBeInTheDocument();
    });
  });

  it("puts the full path in `title`, which truncation may take from the label", () => {
    renderWithStorage();

    const link = screen.getByRole("link", { name: /Main Warehouse/ });
    expect(link).toHaveAttribute("title", "Main Warehouse → Bay 3");
  });
});

/**
 * A quantity with no unit is not a quantity.
 *
 * 2661 of 3243 products in this database record no unit of measure, so the
 * column was a wall of bare numbers. Printing nothing was meant to avoid
 * inventing "pcs" for a product that has no unit — but "10" with nothing
 * after it does not stop a reader assuming pieces, it only moves the
 * invention off the screen and into their head. The slot now always says
 * something: the symbol, or the mark this product uses for a value it does
 * not have.
 */
describe("ItemTable — the unit slot is never empty", () => {
  /** The cell holding the quantity, found by content rather than by index:
   *  module contributors and the date columns move the position around. */
  const quantityCell = () => {
    const row = screen.getByTestId("item-row");
    const num = row.querySelector(".tabular-nums");
    return num?.closest("td");
  };

  it("marks a quantity whose unit is unknown", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    expect(quantityCell()?.textContent).toContain("—");
  });

  it("prints the symbol when the product has one", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[
          makeItem("1", {
            uom: { id: "u1", symbol: "kg", name: "kilogram" },
          } as never),
        ]}
      />,
    );

    expect(quantityCell()?.textContent).toMatch(/kg/i);
    expect(quantityCell()?.textContent).not.toContain("—");
  });

  it("gives the actions room enough not to spill into the quantity", () => {
    // Four 28px icon buttons plus their gaps and the cell's own padding need
    // more than 9rem; under it they overflowed left past the column edge, and
    // a number ended up 7px from a bin icon.
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const cols = document.querySelectorAll("colgroup col");
    const last = cols[cols.length - 1] as HTMLElement;
    expect(parseFloat(last.style.width)).toBeGreaterThanOrEqual(11);
  });
});

/**
 * The actions column is sized from what it holds.
 *
 * It was a round `9rem` nobody had checked against the row, and the four icon
 * buttons overflowed 9px past their own column into the quantity — a number
 * ended up 7px from a bin icon and the two read as one cluster. The width is
 * derived now, and this test is the thing that notices when a fifth action
 * arrives and the constant behind it does not move.
 */
describe("ItemTable — the actions column fits its actions", () => {
  it("counts the same actions the width was derived from", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    const row = screen.getByTestId("item-row");
    const cells = row.querySelectorAll("td");
    const actionsCell = cells[cells.length - 1];
    expect(actionsCell.querySelectorAll("button")).toHaveLength(ACTION_BUTTONS);
  });

  it("separates the destructive action from the safe ones", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    // §2.13a — and the divider is one of the widths the column is sized for.
    const row = screen.getByTestId("item-row");
    const cells = row.querySelectorAll("td");
    const divider = cells[cells.length - 1].querySelector(
      '[aria-hidden="true"]',
    );
    expect(divider).not.toBeNull();
  });
});

describe("ItemTable — the product code is read where it is written", () => {
  /**
   * A scanned barcode is the product's code, so it is stored on the
   * template and the record stays bare. The row asked `item.barcode`
   * alone, so everything that arrived by scan showed no code at all —
   * and the user had no way to confirm the scan had landed.
   */
  it("shows a code that lives on the product template", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[
          makeItem("1", {
            barcode: undefined,
            template: { name: "Kawa", barcode: "5901234512345" },
          } as Partial<Item>),
        ]}
      />,
    );

    expect(screen.getByText("5901234512345")).toBeInTheDocument();
  });

  it("still shows a code that lives on the record itself", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { barcode: "4001234567890" })]}
      />,
    );

    expect(screen.getByText("4001234567890")).toBeInTheDocument();
  });
});

/**
 * The row's actions were unlabelled icons — check circle, +, pencil, bin —
 * and only the accessible names said what they do. Hovering one opened the
 * browser's `title` bubble after a delay, keyboard focus showed nothing at
 * all, and a finger got neither. The words now sit in a tooltip of the app's
 * own, revealed on hover and on focus, with the same text as the accessible
 * name (UI_GUIDELINES §2.13c — a tooltip is not a control, so it carries
 * `pointer-events-none`).
 */
describe("ItemTable — row actions carry their words", () => {
  const NAMES = ["Remove 1 unit", "Add 1 unit", "Edit", "Delete"];

  it("shows every icon action's words in a tooltip, the same words as its name", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    for (const name of NAMES) {
      const button = screen.getByRole("button", { name });
      const tip = within(button).getByRole("tooltip");
      expect(tip).toHaveTextContent(name);
      expect(button.getAttribute("aria-label")).toBe(tip.textContent);
    }
  });

  it("reveals the tooltip on hover and on focus — jsdom has no layout, so this pins the classes that do", () => {
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    for (const name of NAMES) {
      const button = screen.getByRole("button", { name });
      const tip = within(button).getByRole("tooltip");
      expect(button.className).toContain("group/tooltip");
      expect(tip.className).toContain("group-hover/tooltip:opacity-100");
      expect(tip.className).toContain("group-focus-within/tooltip:opacity-100");
      expect(tip.className).toContain("pointer-events-none");
    }
  });

  it("carries the words in the tooltip instead of stacking the browser's own bubble on top", () => {
    // `title` is the usual spelling of this tooltip and answers hover only;
    // kept beside the app's own tooltip it opens a second bubble over the
    // first. The words live in one place now — here and in the name.
    render(<ItemTable {...baseProps} items={[makeItem("1")]} />);

    for (const name of NAMES) {
      const button = screen.getByRole("button", { name });
      expect(button).not.toHaveAttribute("title");
    }
  });
});

describe("ItemTable — an account that cannot write", () => {
  it("shows the quantity but offers no stock alert", () => {
    render(
      <ItemTable
        {...baseProps}
        items={[makeItem("1", { quantity: "4" })]}
        canWrite={false}
      />,
    );

    expect(screen.queryByTitle("Set stock alert")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /set stock alert/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });
});
