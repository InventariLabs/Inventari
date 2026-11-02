import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { StorageItemsTable } from "./StorageItemsTable";
import { StorageItemsCards } from "./StorageItemsCards";
import { tFor } from "@/test/mocks/i18n";
import { formatDate } from "@/utils/formatters";
import type { Item } from "@/types";

// Real translator: the two column labels this spec distinguishes are only
// distinguishable if the keys actually resolve.
const t = tFor("locations");

const item: Item = {
  is_deleted: false,
  id: "item-1",
  location_id: "storage-1",
  category_id: null,
  name: "Apple Juice",
  brand: null,
  description: null,
  weight: null,
  quantity: "3",
  added_date: "2026-01-01",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

const props = {
  t,
  filteredItems: [item],
  onItemClick: vi.fn(),
  onConsumeItem: vi.fn(),
  onEditItem: vi.fn(),
  onDeleteItem: vi.fn(),
  isConsumePending: false,
  consumePendingId: undefined,
  isDeletePending: false,
  getCategoryName: () => "",
};

describe("StorageItemsTable date column", () => {
  it("shows effective expiry on both the table and the phone card", () => {
    const opened = {
      ...item,
      expiry_date: "2026-12-31",
      effective_expiry_date: "2020-01-02",
    };
    render(
      <>
        <StorageItemsTable {...props} filteredItems={[opened]} />
        <StorageItemsCards {...props} filteredItems={[opened]} />
      </>,
    );
    expect(screen.getAllByText(formatDate("2020-01-02"))).toHaveLength(2);
    expect(screen.queryByText(formatDate("2026-12-31"))).toBeNull();
  });
  it("names the date column after freezing where the type freezes", () => {
    render(<StorageItemsTable {...props} behaviorMode="FREEZING" />);

    expect(screen.getByText("Freezing Date")).toBeInTheDocument();
    expect(screen.queryByText("Added")).not.toBeInTheDocument();
  });

  it("names it after adding everywhere else", () => {
    render(<StorageItemsTable {...props} behaviorMode="EXPIRY" />);

    expect(screen.getByText("Added")).toBeInTheDocument();
    expect(screen.queryByText("Freezing Date")).not.toBeInTheDocument();
  });

  it("names it after adding when the location declares no mode", () => {
    render(<StorageItemsTable {...props} />);

    expect(screen.getByText("Added")).toBeInTheDocument();
  });

  it("shows the date the item was added under the 'Added' header", () => {
    render(
      <StorageItemsTable
        {...props}
        filteredItems={[{ ...item, added_date: "2026-03-04" }]}
        behaviorMode="EXPIRY"
      />,
    );

    expect(screen.getByText(formatDate("2026-03-04"))).toBeInTheDocument();
  });

  it("shows the freezing date where the type freezes", () => {
    render(
      <StorageItemsTable
        {...props}
        filteredItems={[
          { ...item, added_date: "2026-03-04", freeze_date: "2026-05-06" },
        ]}
        behaviorMode="FREEZING"
      />,
    );

    expect(screen.getByText(formatDate("2026-05-06"))).toBeInTheDocument();
    expect(
      screen.queryByText(formatDate("2026-03-04")),
    ).not.toBeInTheDocument();
  });

  it("renders a missing freezing date the way the rest of the app does", () => {
    render(
      <StorageItemsTable
        {...props}
        filteredItems={[{ ...item, freeze_date: null }]}
        behaviorMode="FREEZING"
      />,
    );

    expect(screen.getAllByText("-").length).toBeGreaterThan(0);
    expect(screen.queryByText("None")).not.toBeInTheDocument();
  });
});

describe("the location table reads at the products list size", () => {
  it("carries the products list column-header type classes", () => {
    render(<StorageItemsTable {...props} />);

    const header = screen.getByRole("columnheader", { name: "Product" });

    expect(header.closest("tr")).toHaveClass(
      "text-xs",
      "font-medium",
      "uppercase",
      "tracking-wider",
      "text-on-muted",
    );
  });

  it("names the record at the record-name step, not base size", () => {
    render(<StorageItemsTable {...props} />);

    expect(screen.getByText("Apple Juice")).toHaveClass(
      "text-sm",
      "font-semibold",
      "text-on",
    );
  });

  it("shows a partly used pack as the fraction left on the table and card", () => {
    const rice = {
      ...item,
      quantity: "0.900",
      uom: { symbol: "pack", rounding: "1.000000" } as Item["uom"],
    };
    render(
      <>
        <StorageItemsTable {...props} filteredItems={[rice]} />
        <StorageItemsCards {...props} filteredItems={[rice]} />
      </>,
    );

    // The table cell, then the card's badge and its category line.
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
    );
    const amounts: string[] = [];
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent?.trim() ?? "";
      if (/^\d+(\.\d+)?$/.test(text)) amounts.push(text);
    }
    expect(amounts).toEqual(["0.9", "0.9", "0.9"]);
  });

  it("sets the quantity as data with tabular figures", () => {
    render(<StorageItemsTable {...props} />);

    expect(screen.getByText("3")).toHaveClass("text-sm", "tabular-nums");
  });

  it("declares the dates at the data step instead of inheriting", () => {
    render(
      <StorageItemsTable
        {...props}
        filteredItems={[{ ...item, added_date: "2026-03-04" }]}
      />,
    );

    expect(
      screen.getByText(formatDate("2026-03-04")).closest("div"),
    ).toHaveClass("text-xs");
  });

  it("declares the shelf at the data step instead of inheriting", () => {
    render(
      <StorageItemsTable
        {...props}
        filteredItems={[{ ...item, shelf_location: "Shelf A" }]}
      />,
    );

    expect(screen.getByText("Shelf A")).toHaveClass("text-xs");
  });
});
