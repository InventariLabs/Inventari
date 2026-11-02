import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

import { StorageItemsEmpty } from "@/modules/spaces/components/StorageItems/StorageItemsEmpty";
import { StorageItemsFilters } from "@/modules/spaces/components/StorageItems/StorageItemsFilters";

import type { CategoryDTO } from "@/types";

// ── mocks ─────────────────────────────────────────────────────────────────────

vi.mock("@/contexts/ModulesContext", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ModulesProvider: ({ children }: any) => children,
  useModules: () => ({
    enabledModules: ["core", "spaces", "inventory"],
    isLoading: false,
    isModuleEnabled: () => true,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  storagesApi: {
    printLabel: vi.fn().mockResolvedValue(new Blob()),
  },
  itemsApi: {
    exportXlsx: vi.fn().mockResolvedValue(new Blob()),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    loading: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    dismiss: vi.fn(),
  },
}));

// ── fixtures ──────────────────────────────────────────────────────────────────

const t = (key: string, opts?: { defaultValue?: string }) =>
  opts?.defaultValue ?? key;

const mockCategories: CategoryDTO[] = [
  {
    id: "cat-1",
    name: "Dairy",
    code: null,
    icon: null,
    is_active: true,
    is_module_owned: false,
  } as unknown as CategoryDTO,
  {
    id: "cat-2",
    name: "Vegetables",
    code: null,
    icon: null,
    is_active: true,
    is_module_owned: false,
  } as unknown as CategoryDTO,
];

// ── StorageItemsEmpty ─────────────────────────────────────────────────────────

describe("StorageItemsEmpty", () => {
  it("renders add item link", () => {
    render(
      <MemoryRouter>
        <StorageItemsEmpty t={t} storageId="loc-1" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link");
    expect(link).toBeInTheDocument();
  });

  // An archived location takes no new products: the server refuses the
  // write, so the invitation was a promise the screen could not keep.
  it("offers no way to add a product when the location is archived", () => {
    render(
      <MemoryRouter>
        <StorageItemsEmpty t={t} storageId="loc-1" isArchived />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("link contains storageId in href", () => {
    render(
      <MemoryRouter>
        <StorageItemsEmpty t={t} storageId="loc-42" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toContain("loc-42");
  });

  it("renders empty state icon or text", () => {
    render(
      <MemoryRouter>
        <StorageItemsEmpty t={t} storageId="loc-1" />
      </MemoryRouter>,
    );
    // Container renders without crash
    expect(document.querySelector(".text-center")).toBeTruthy();
  });
});

// ── StorageItemsFilters ───────────────────────────────────────────────────────

describe("StorageItemsFilters", () => {
  it("returns null when itemCount is 0", () => {
    const { container } = render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={mockCategories}
        hasUncategorized={false}
        selectedCategoryId={null}
        onSelectCategory={vi.fn()}
        itemCount={0}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders All filter button when itemCount > 0", () => {
    render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={mockCategories}
        hasUncategorized={false}
        selectedCategoryId="ALL"
        onSelectCategory={vi.fn()}
        itemCount={5}
      />,
    );
    // All button via t("common:filterAll") returns key
    expect(
      screen.getByText(/common:filterAll|Wszystko|All/),
    ).toBeInTheDocument();
  });

  it("renders category names", () => {
    render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={mockCategories}
        hasUncategorized={false}
        selectedCategoryId="ALL"
        onSelectCategory={vi.fn()}
        itemCount={5}
      />,
    );
    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.getByText("Vegetables")).toBeInTheDocument();
  });

  it("calls onSelectCategory when a category button is clicked", () => {
    const onSelectCategory = vi.fn();
    render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={mockCategories}
        hasUncategorized={false}
        selectedCategoryId="ALL"
        onSelectCategory={onSelectCategory}
        itemCount={5}
      />,
    );
    const dairyBtn = screen.getByText("Dairy").closest("button")!;
    fireEvent.click(dairyBtn);
    expect(onSelectCategory).toHaveBeenCalledWith("cat-1");
  });

  it("de-selects category on second click (calls with ALL)", () => {
    const onSelectCategory = vi.fn();
    render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={mockCategories}
        hasUncategorized={false}
        selectedCategoryId="cat-1"
        onSelectCategory={onSelectCategory}
        itemCount={5}
      />,
    );
    const dairyBtn = screen.getByText("Dairy").closest("button")!;
    fireEvent.click(dairyBtn);
    expect(onSelectCategory).toHaveBeenCalledWith("ALL");
  });

  it("renders uncategorized button when hasUncategorized is true", () => {
    render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={[]}
        hasUncategorized={true}
        selectedCategoryId="ALL"
        onSelectCategory={vi.fn()}
        itemCount={3}
      />,
    );
    // 2 buttons: All + Uncategorized
    expect(screen.getAllByRole("button").length).toBe(2);
  });

  it("keeps every chip on one line in a scrollbar-free scroll row", () => {
    const { container } = render(
      <StorageItemsFilters
        t={t}
        usedCategoriesData={mockCategories}
        hasUncategorized={true}
        selectedCategoryId={null}
        onSelectCategory={vi.fn()}
        itemCount={5}
      />,
    );
    // Long category names overflow the row instead of squashing the chips:
    // every control keeps its label on one line and the row scrolls.
    const chips = Array.from(container.querySelectorAll("button"));
    expect(chips.length).toBeGreaterThanOrEqual(4);
    for (const chip of chips) {
      expect(chip.className).toContain("shrink-0");
      expect(chip.className).toContain("whitespace-nowrap");
    }
    // The track hides its scrollbar with real CSS (ScrollRow), not with a
    // class that is defined nowhere.
    const track = container.firstElementChild as HTMLElement;
    expect(track.className).toContain("scrollbar-width:none");
  });
});
