import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import StorageItemsSection from "./StorageItemsSection";
import { tFor } from "@/test/mocks/i18n";
import type { Item, CategoryDTO } from "@/types";

// Real translator: with an identity stub the empty-state assertion below
// held whether or not storages:detail.empty existed.
const t = tFor("locations");

const makeItem = (overrides: Partial<Item> = {}): Item => ({
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
  is_deleted: false,
  ...overrides,
});

const defaultProps = {
  t,
  storageId: "storage-1",
  behaviorMode: "EXPIRY",
  filteredItems: [],
  items: [],
  usedCategoriesData: [] as CategoryDTO[],
  hasUncategorized: false,
  selectedCategoryId: null,
  onSelectCategory: vi.fn(),
  onItemClick: vi.fn(),
  onConsumeItem: vi.fn(),
  onEditItem: vi.fn(),
  onDeleteItem: vi.fn(),
  isConsumePending: false,
  consumePendingId: undefined,
  isDeletePending: false,
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <BrowserRouter>{children}</BrowserRouter>
);

describe("StorageItemsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when no items", () => {
    render(<StorageItemsSection {...defaultProps} />, { wrapper });
    expect(screen.getByText("This location is empty")).toBeInTheDocument();
  });

  it("heads the list with a record count, not a product count", () => {
    const items = [
      makeItem({ id: "item-1", name: "Apple Juice" }),
      makeItem({ id: "item-2", name: "Apple Juice" }),
      makeItem({ id: "item-3", name: "Apple Juice" }),
    ];
    render(
      <StorageItemsSection
        {...defaultProps}
        filteredItems={items}
        items={items}
      />,
      { wrapper },
    );
    expect(
      screen.getByRole("heading", { name: "Records (3)" }),
    ).toBeInTheDocument();
  });

  it("renders item names when filteredItems provided", () => {
    const items = [
      makeItem({ id: "item-1", name: "Apple Juice" }),
      makeItem({ id: "item-2", name: "Milk" }),
    ];
    render(
      <StorageItemsSection
        {...defaultProps}
        filteredItems={items}
        items={items}
      />,
      { wrapper },
    );
    expect(screen.getAllByText("Apple Juice").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Milk").length).toBeGreaterThan(0);
  });

  it("calls onItemClick when item name clicked on desktop table", () => {
    const item = makeItem({ id: "item-1", name: "Tomato Paste" });
    const onItemClick = vi.fn();
    render(
      <StorageItemsSection
        {...defaultProps}
        filteredItems={[item]}
        items={[item]}
        onItemClick={onItemClick}
      />,
      { wrapper },
    );
    // Desktop table renders name in a clickable div
    const nameEl = screen.getAllByText("Tomato Paste")[0];
    fireEvent.click(nameEl);
    expect(onItemClick).toHaveBeenCalledWith(item);
  });

  it("renders category filter buttons when usedCategoriesData provided", () => {
    const category: CategoryDTO = {
      is_active: true,
      is_module_owned: false,
      field_definitions: [],
      id: "cat-1",
      name: "Vegetables",
      code: null,
      icon: null,
      sort_order: 1,
      context_tag: null,
    };
    // The section reads only the code and the name off the category, which
    // both serializations carry; the DTO is what the test builds.
    const item = makeItem({
      id: "item-1",
      name: "Carrot",
      category_id: "cat-1",
      category: category as unknown as Item["category"],
    });
    render(
      <StorageItemsSection
        {...defaultProps}
        filteredItems={[item]}
        items={[item]}
        usedCategoriesData={[category]}
      />,
      { wrapper },
    );
    expect(screen.getAllByText("Vegetables").length).toBeGreaterThan(0);
  });
});
