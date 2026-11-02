/**
 * The stock search answers with records, not catalogue entries: two pallets of
 * the same flour are two results carrying one product_template_id, and a
 * record catalogued as nothing carries none at all. Keying the list by that
 * id gave React repeated keys — a console full of warnings on every open, and
 * a list whose rows React is free to reuse for the wrong record.
 *
 * The rows also have to read differently once rendered: a date, a serial or
 * the shelf is what tells two records of one product apart — and each of
 * those prints through a label passed down from the editor, so the tests
 * below render the dropdown the way the row does, labels included.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";

import { LineItemSearchDropdown } from "./LineItemSearchDropdown";
import type { LineItemProduct, LineItemSearchState } from "./types";

type ScopeProp = LineItemSearchState["scope"];

const TEMPLATE = "22e3f5e6-0000-4000-8000-000000000001";

function stockHit(overrides: Partial<LineItemProduct>): LineItemProduct {
  return {
    product_template_id: TEMPLATE,
    item_id: null,
    name: "Flour",
    sku: null,
    barcode: null,
    brand: null,
    image_url: null,
    uom_id: null,
    ...overrides,
  };
}

function renderList(results: LineItemProduct[]) {
  return render(
    <LineItemSearchDropdown
      results={results}
      isLoading={false}
      selectedIndex={-1}
      lineName="flo"
      noResultsLabel="Nothing found"
      onSelect={vi.fn()}
    />,
  );
}

describe("LineItemSearchDropdown — one row per record", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the keys apart for two records of one template", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});

    renderList([
      stockHit({ item_id: "item-a", name: "Flour — shelf A" }),
      stockHit({ item_id: "item-b", name: "Flour — shelf B" }),
    ]);

    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(
      errors.mock.calls.some((call) => String(call[0]).includes("same key")),
    ).toBe(false);
  });

  it("keeps them apart for records catalogued as nothing", () => {
    // Both hits carry product_template_id: null — the shape the endpoint
    // documents for stock that was never linked to a template.
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});

    renderList([
      stockHit({
        product_template_id: null,
        item_id: "item-c",
        name: "Loose flour",
      }),
      stockHit({
        product_template_id: null,
        item_id: "item-d",
        name: "Loose sugar",
      }),
    ]);

    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(
      errors.mock.calls.some((call) => String(call[0]).includes("same key")),
    ).toBe(false);
  });

  it("still lists catalogue hits, which name a template and no record", () => {
    renderList([
      stockHit({ item_id: undefined, name: "Flour" }),
      stockHit({
        product_template_id: "22e3f5e6-0000-4000-8000-000000000002",
        item_id: undefined,
        name: "Sugar",
      }),
    ]);

    expect(screen.getAllByRole("option")).toHaveLength(2);
  });
});

describe("LineItemSearchDropdown — same product, two rows", () => {
  const base = {
    product_template_id: "t-1",
    name: "Yogurt",
    sku: null,
    barcode: null,
    brand: null,
    image_url: null,
    uom_id: null,
  };

  it("shows the best-before that makes two rows of one product two rows", () => {
    const rows: LineItemProduct[] = [
      {
        ...base,
        item_id: "i-1",
        available_quantity: 10,
        expiry_date: "2026-01-01",
      },
      {
        ...base,
        item_id: "i-2",
        available_quantity: 2,
        expiry_date: "2026-02-01",
      },
    ];
    render(
      <LineItemSearchDropdown
        results={rows}
        isLoading={false}
        selectedIndex={-1}
        lineName="Yogurt"
        noResultsLabel="Nothing"
        inStockLabel="In stock"
        expiryLabel="Expiry date"
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText(/expiry date: 2026-01-01/i)).toBeInTheDocument();
    expect(screen.getByText(/expiry date: 2026-02-01/i)).toBeInTheDocument();
  });

  it("shows the serial of a tracked row", () => {
    const rows: LineItemProduct[] = [
      {
        ...base,
        item_id: "i-9",
        available_quantity: 1,
        serial_number: "SN-77",
      },
    ];
    render(
      <LineItemSearchDropdown
        results={rows}
        isLoading={false}
        selectedIndex={-1}
        lineName="Yogurt"
        noResultsLabel="Nothing"
        inStockLabel="In stock"
        expiryLabel="Expiry date"
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("SN-77")).toBeInTheDocument();
  });

  it("names the shelf a hit stands on", () => {
    // The search walks a location's subtree, so same-named rows can stand on
    // different shelves; the shelf is what tells them apart.
    const rows: LineItemProduct[] = [
      {
        ...base,
        item_id: "i-1",
        available_quantity: 4,
        expiry_date: "2026-01-01",
        location_name: "Regal — Shelf A",
      },
      {
        ...base,
        item_id: "i-2",
        available_quantity: 10,
        expiry_date: "2026-01-01",
        location_name: "Regal",
      },
    ];
    render(
      <LineItemSearchDropdown
        results={rows}
        isLoading={false}
        selectedIndex={-1}
        lineName="Yogurt"
        noResultsLabel="Nothing"
        inStockLabel="In stock"
        storageLabel="Location"
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText(/location: regal — shelf a/i)).toBeInTheDocument();
    expect(screen.getByText(/location: regal$/i)).toBeInTheDocument();
  });
});

describe("LineItemSearchDropdown — the overlay stack can see the panel", () => {
  it("carries the picker marker even when it holds no results", () => {
    // `hasListboxOpen` reads the DOM: the panel with results is a listbox,
    // but the empty one is not a listbox at all — only the marker says a
    // picker is open, so an Escape aimed at the empty panel closes the panel
    // instead of the sheet around it.
    renderList([]);

    expect(
      document.querySelector("[data-line-item-dropdown]"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByText("Nothing found")).toBeInTheDocument();
  });

  it("stays closed until there is a result or a search worth reporting", () => {
    // Focusing an empty product field used to open the panel with "no
    // results" printed before anything had been searched.
    render(
      <LineItemSearchDropdown
        results={[]}
        isLoading={false}
        selectedIndex={-1}
        lineName=""
        noResultsLabel="Nothing found"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.queryByText("Nothing found")).not.toBeInTheDocument();
    expect(document.querySelector("[data-line-item-dropdown]")).toBeNull();
  });
});

describe("LineItemSearchDropdown — twins created the same day", () => {
  const base = {
    product_template_id: "t-1",
    name: "RV2172 Twin",
    sku: null,
    barcode: null,
    brand: null,
    image_url: null,
    uom_id: null,
    available_quantity: null as number | null,
    created_at: "2026-09-15T21:56:42.973Z",
  };

  it("still tells same-day records apart by their record code", () => {
    // Two records created 32 ms apart share the landing date, so the day
    // alone left both rows saying the same thing except the quantity.
    const rows: LineItemProduct[] = [
      {
        ...base,
        item_id: "0198aaaa-0000-7000-8000-00000000aa01",
        available_quantity: 1,
      },
      {
        ...base,
        item_id: "0198aaaa-0000-7000-8000-00000000bb02",
        available_quantity: 1,
      },
    ];

    renderList(rows);

    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.getByText("#00aa01")).toBeInTheDocument();
    expect(screen.getByText("#00bb02")).toBeInTheDocument();
  });

  it("leaves the record code off rows that already differ", () => {
    const rows: LineItemProduct[] = [
      {
        ...base,
        item_id: "0198aaaa-0000-7000-8000-00000000aa01",
        available_quantity: 1,
      },
      {
        ...base,
        item_id: "0198aaaa-0000-7000-8000-00000000bb02",
        available_quantity: 5,
      },
    ];

    renderList(rows);

    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.queryByText("#00aa01")).not.toBeInTheDocument();
    expect(screen.queryByText("#00bb02")).not.toBeInTheDocument();
  });
});

describe("LineItemSearchDropdown — same-named catalogue products", () => {
  it("tells them apart once their generated SKUs are hidden", () => {
    // Catalogue hits carry no record id. Two products named alike used to
    // differ by the STM- code the server minted; with that code hidden the
    // two options read the same and a line could land on the wrong one.
    renderList([
      stockHit({
        product_template_id: "183c9530-e37a-426b-9373-153e0b405954",
        name: "Soy wax",
        sku: "STM-16D83E65",
      }),
      stockHit({
        product_template_id: "a877d7d4-39c7-47ba-8550-845d2fd8cd52",
        name: "Soy wax",
        sku: "STM-742BF620",
        brand: "Second brand",
      }),
      stockHit({
        product_template_id: "0d1e0000-0000-4000-8000-000000000003",
        name: "Wick",
        sku: "STM-0A0B0C0D",
      }),
    ]);

    const names = screen.getAllByRole("option").map((o) => o.textContent);
    expect(new Set(names).size).toBe(3);
    expect(screen.queryByText(/STM-/)).not.toBeInTheDocument();
    expect(screen.getByText("#405954")).toBeInTheDocument();
    expect(screen.getByText("Second brand · #d8cd52")).toBeInTheDocument();
    // The uniquely named product needs no tie-breaker.
    expect(screen.queryByText("#000003")).not.toBeInTheDocument();
  });
});

describe("LineItemSearchDropdown — limited to a source location", () => {
  const scope = (overrides: Partial<NonNullable<ScopeProp>> = {}) => ({
    hint: "Products in Dry Goods",
    elsewhere: [] as LineItemProduct[],
    elsewhereLabel: (storage: string) => `in ${storage}`,
    changeLabel: "Change source location",
    onChange: vi.fn(),
    ...overrides,
  });

  function renderScoped(
    results: LineItemProduct[],
    scopeProp: NonNullable<ScopeProp>,
  ) {
    return render(
      <LineItemSearchDropdown
        results={results}
        isLoading={false}
        selectedIndex={-1}
        lineName="Gouda"
        noResultsLabel="Nothing found"
        scope={scopeProp}
        onSelect={vi.fn()}
      />,
    );
  }

  it("says which location the list is limited to", () => {
    renderScoped([stockHit({ item_id: "i-1", name: "Flour" })], scope());

    expect(screen.getByText("Products in Dry Goods")).toBeInTheDocument();
  });

  it("shows where a product stands when the source holds none of it", async () => {
    const onChange = vi.fn();
    const onRequestClose = vi.fn();
    render(
      <LineItemSearchDropdown
        results={[]}
        isLoading={false}
        selectedIndex={-1}
        lineName="Gouda"
        noResultsLabel="Nothing found"
        scope={scope({
          onChange,
          elsewhere: [
            stockHit({ name: "Gouda Cheese", location_name: "Fridge B" }),
          ],
        })}
        onRequestClose={onRequestClose}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Gouda Cheese")).toBeInTheDocument();
    expect(screen.getByText("in Fridge B")).toBeInTheDocument();
    // It is information, not a choice: picking it would put a line on the
    // document that the source location cannot supply.
    expect(screen.queryByRole("option")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Change source location" }),
    );
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onRequestClose).toHaveBeenCalledTimes(1);
  });

  it("offers no way out when the product stands nowhere else either", () => {
    renderScoped([], scope());

    expect(screen.getByText("Nothing found")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Change source location" }),
    ).not.toBeInTheDocument();
  });
});

describe("LineItemSearchDropdown — a name nothing on the list matches", () => {
  function renderEmpty(onCreate?: () => void) {
    return render(
      <LineItemSearchDropdown
        results={[]}
        isLoading={false}
        selectedIndex={-1}
        lineName="Dell laptop"
        noResultsLabel="Nothing found"
        createLabel="Add “Dell laptop” as a new product"
        onCreate={onCreate}
        onSelect={vi.fn()}
      />,
    );
  }

  it("offers to make the name a product", async () => {
    const onCreate = vi.fn();
    renderEmpty(onCreate);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Add “Dell laptop” as a new product",
      }),
    );

    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it("offers nothing where a line may stay as typed", () => {
    renderEmpty();

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
