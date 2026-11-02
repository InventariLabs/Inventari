import type { ReactElement } from "react";
import {
  render as rtlRender,
  screen,
  fireEvent,
  type RenderOptions,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ItemMobileCard from "./ItemMobileCard";
import ItemTable from "./ItemTable";
import BulkEditModal from "./BulkEditModal";
import type { CategoryDTO, Item, StorageLocation } from "@/types";
import { makeStorageSummary } from "@/test/factories/storage";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { QueryWrapper } from "@/test/queryWrapper";

// The rows read the unit catalogue to restate a partly used package.
const render = (ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) =>
  rtlRender(ui, { wrapper: QueryWrapper, ...options });

// ── mocks ──────────────────────────────────────────────────────────────────────

vi.mock("@/utils/helpers", () => ({
  formatDate: vi.fn(() => "01 Jan 2025"),
  isExpired: vi.fn(() => false),
  isExpiringSoon: vi.fn(() => false),
  getStorageLocationPath: vi.fn((s: StorageLocation) => s.name),
  splitLocationPath: vi.fn((path: string) => ({ leaf: path, parents: null })),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    dismiss: vi.fn(),
  },
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: vi.fn(() => "PLN"),
}));

vi.mock("@/modules/shared/hooks/useStorages", () => ({
  useStorages: vi.fn(() => ({ data: [] })),
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCategories: vi.fn(() => ({ data: [] })),
  useScopedCategories: vi.fn(() => ({ all: [], scoped: [] })),
}));

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useBulkUpdateItems: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: vi.fn(() => ({
    enabledModules: [],
    isLoading: false,
    isModuleEnabled: () => false,
    refreshModules: vi.fn(),
  })),
}));

// The stats module's "Show inventory value" switch; on unless a test turns it
// off, as for an organization without the stats module.
const inventoryValue = { shown: true };
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => inventoryValue.shown,
}));

// ── factories ─────────────────────────────────────────────────────────────────

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "item-1",
    name: "Test Item",
    location_id: "loc-1",
    category_id: null,
    brand: null,
    description: null,
    weight: null,
    quantity: "5",
    added_date: "2024-01-01",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    is_deleted: false,
    deleted_at: null,
    deletion_reason: null,
    created_at: "2024-01-01",
    updated_at: "2024-01-01",
    min_quantity: null,
    ...overrides,
  };
}

const makeStorage = makeStorageSummary;

function makeCategory(overrides: Partial<CategoryDTO> = {}): CategoryDTO {
  return {
    id: "cat-1",
    name: "Dairy",
    code: null,
    icon: "Package",
    sort_order: 0,
    context_tag: null,
    is_active: true,
    is_module_owned: false,
    ...overrides,
  };
}

// ── ItemMobileCard ────────────────────────────────────────────────────────────

describe("ItemMobileCard", () => {
  const onItemClick = vi.fn();
  const onConsume = vi.fn();
  const onEdit = vi.fn();
  const onSetThreshold = vi.fn();
  const onToggleSelect = vi.fn();
  const onOpenActions = vi.fn();

  const defaultProps = {
    onItemClick,
    onConsume,
    onEdit,
    onSetThreshold,
    onOpenActions,
    consumingId: null,
    isSelected: false,
    onToggleSelect,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the item name", () => {
    render(
      <ItemMobileCard item={makeItem({ name: "Milk" })} {...defaultProps} />,
    );
    expect(screen.getByText("Milk")).toBeInTheDocument();
  });

  it("renders the quantity", () => {
    render(
      <ItemMobileCard item={makeItem({ quantity: "12" })} {...defaultProps} />,
    );
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders storage name when storages provided", () => {
    render(
      <ItemMobileCard
        item={makeItem({ location_id: "loc-1" })}
        storages={[makeStorage({ id: "loc-1", name: "Pantry" })]}
        {...defaultProps}
      />,
    );
    expect(screen.getByText("Pantry")).toBeInTheDocument();
  });

  it("renders category name when categories provided", () => {
    render(
      <ItemMobileCard
        item={makeItem({ category_id: "cat-1" })}
        categories={[makeCategory({ id: "cat-1", name: "Dairy" })]}
        {...defaultProps}
      />,
    );
    expect(screen.getByText("Dairy")).toBeInTheDocument();
  });

  it("calls onItemClick when main info area is clicked", () => {
    render(<ItemMobileCard item={makeItem()} {...defaultProps} />);
    fireEvent.click(screen.getByText("Test Item"));
    expect(onItemClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "item-1" }),
    );
  });

  it("calls onSetThreshold when quantity button is clicked", () => {
    render(
      <ItemMobileCard item={makeItem({ quantity: "7" })} {...defaultProps} />,
    );
    fireEvent.click(screen.getByTitle("Set stock alert"));
    expect(onSetThreshold).toHaveBeenCalledWith(
      expect.objectContaining({ id: "item-1" }),
    );
  });
});

// ── ItemTable ─────────────────────────────────────────────────────────────────

function renderTable(items: Item[], extra = {}) {
  return render(
    <MemoryRouter>
      <ItemTable
        items={items}
        enabledModules={["items"]}
        onItemClick={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onSetThreshold={vi.fn()}
        consumingId={null}
        selectedIds={[]}
        onToggleSelect={vi.fn()}
        onSelectAll={vi.fn()}
        {...extra}
      />
    </MemoryRouter>,
  );
}

describe("ItemTable", () => {
  it("renders table header columns", () => {
    renderTable([]);
    expect(screen.getByText("Product")).toBeInTheDocument();
    expect(screen.getByText("Location")).toBeInTheDocument();
    expect(screen.getByText("Quantity")).toBeInTheDocument();
  });

  it("renders item name for each item", () => {
    renderTable([
      makeItem({ name: "Butter" }),
      makeItem({ id: "item-2", name: "Eggs" }),
    ]);
    expect(screen.getByText("Butter")).toBeInTheDocument();
    expect(screen.getByText("Eggs")).toBeInTheDocument();
  });

  it("calls onToggleSelect when row checkbox is clicked", () => {
    const onToggleSelect = vi.fn();
    renderTable([makeItem()], { onToggleSelect });
    // First checkbox is select-all, second is row checkbox
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    expect(onToggleSelect).toHaveBeenCalledWith("item-1");
  });

  it("calls onSelectAll(all ids) when header checkbox is clicked and nothing selected", () => {
    const onSelectAll = vi.fn();
    renderTable([makeItem(), makeItem({ id: "item-2", name: "Egg" })], {
      onSelectAll,
      selectedIds: [],
    });
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(onSelectAll).toHaveBeenCalledWith(["item-1", "item-2"]);
  });
});

// ── BulkEditModal ─────────────────────────────────────────────────────────────

describe("BulkEditModal", () => {
  const onClose = vi.fn();
  const onSuccess = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
    onSuccess.mockClear();
    inventoryValue.shown = true;
  });

  // A bulk edit writes the purchase price into every selected record, so it
  // follows the same switch as the item form: where stock value is not
  // shown the price feeds nothing on screen, and the edit does not offer it.
  it("offers the price where the inventory value is shown", () => {
    render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );
    expect(
      screen.getByRole("checkbox", { name: /Price \(PLN\)/ }),
    ).toBeInTheDocument();
  });

  it("does not offer the price where the inventory value is not shown", () => {
    inventoryValue.shown = false;
    render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );
    expect(
      screen.queryByRole("checkbox", { name: /Price \(PLN\)/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Brand/ })).toBeInTheDocument();
  });

  it("renders dialog with item count in title", () => {
    render(
      <BulkEditModal
        itemIds={["a", "b", "c"]}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Bulk Edit.*3/i)).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders "Apply changes" submit button', () => {
    render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );
    expect(screen.getByText("Apply changes")).toBeInTheDocument();
  });

  it("warns in words and an icon — never an emoji baked into the translation", () => {
    // The catalogue string carried "⚠️" before, so every language read the
    // glyph aloud and the wording could not travel without it. The icon is
    // decorative: the adjacent text already says "Warning".
    const { container } = render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );

    const label = screen.getByText("Warning:");
    expect(label).toHaveTextContent(/^Warning:$/);
    expect(container.textContent).not.toContain("⚠");
    const icon = label.closest("p")?.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("renders field toggle checkboxes", () => {
    render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );
    expect(screen.getByText("Location")).toBeInTheDocument();
    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText("Brand")).toBeInTheDocument();
  });

  it("names a category the way the picker does — by code, not by the record", () => {
    // The form translates `deli` to "Cold cuts"; bulk edit printing the
    // raw record name put the same category thirty rows apart in the same
    // alphabet, and a reader who filed products under "Cold cuts" could
    // not find them here.
    const deli = {
      id: "cat-deli",
      name: "Deli",
      code: "deli",
      context_tag: null,
      group_label: null,
      icon: null,
      sort_order: 0,
      meta_data: null,
      is_module_owned: false,
      module_name: null,
      is_active: true,
      field_definitions: [],
    } as unknown as CategoryDTO;
    vi.mocked(useScopedCategories).mockReturnValue({
      all: [deli],
      scoped: [deli],
      error: null,
      refetch: vi.fn(),
    });

    render(
      <BulkEditModal itemIds={["a"]} onClose={onClose} onSuccess={onSuccess} />,
    );
    fireEvent.click(screen.getByText("Category"));

    expect(
      screen.getByRole("option", { name: "Cold cuts" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Deli" })).toBeNull();
  });
});
