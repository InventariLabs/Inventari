import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@/test/utils";
import { serveLocations } from "@/test/serveLocations";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MoveItemModal } from "./MoveItemModal";
import ThresholdQuickSetSheet from "./ThresholdQuickSetSheet";
import CategoryCreateModal from "./CategoryCreateModal";
import { CategoryFormModal } from "./CategoryFormModal";
import {
  useCreateCategory,
  useUpdateCategory,
} from "@/modules/shared/hooks/useCategories";
import type { Item, StorageLocation, CategoryDTO } from "@/types";

// ── mocks ──────────────────────────────────────────────────────────────────────

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useMoveItem: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useUpdateItem: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

const storageLocations = vi.hoisted(() =>
  [
    { id: "loc-1", name: "Shelf A" },
    { id: "loc-2", name: "Shelf B" },
  ].map((base) => ({
    ...base,
    parent_id: null,
    is_leaf: true,
    location_type_id: null,
    organization_id: "org-1",
    usage: "internal",
    description: null,
    location_details: null,
    settings: null,
    created_at: "",
    context_schema: [],
    behavior_mode: "standard",
    field_definitions: [],
    context_tag: null,
    is_module_owned: false,
  })),
);

vi.mock("@/lib/api/mutationFactory", () => ({
  useAppMutation: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/lib/api/categories", () => ({
  categoriesApi: { create: vi.fn() },
}));

vi.mock("@/components/ui/FieldBuilder", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/ui/FieldBuilder")>()),
  default: () => <div data-testid="field-builder" />,
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCreateCategory: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useUpdateCategory: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/utils/helpers", () => ({
  LOCATION_PATH_SEPARATOR: " › ",
  getStorageLocationPath: vi.fn((s: StorageLocation) => s.name),
  formatDate: vi.fn(() => ""),
  isExpired: vi.fn(() => false),
  isExpiringSoon: vi.fn(() => false),
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

function makeCategory(overrides: Partial<CategoryDTO> = {}): CategoryDTO {
  return {
    id: "cat-1",
    name: "Dairy",
    code: null,
    icon: "Package",
    sort_order: 0,
    field_definitions: [],
    context_tag: null,
    is_active: true,
    is_module_owned: false,
    ...overrides,
  };
}

// ── MoveItemModal ─────────────────────────────────────────────────────────────

describe("MoveItemModal", () => {
  const onClose = vi.fn();
  const onSuccess = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
    onSuccess.mockClear();
  });

  it("renders dialog with move title", () => {
    render(
      <MoveItemModal
        item={makeItem()}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Move/i })).toBeInTheDocument();
  });

  it("renders item name in prompt text", () => {
    render(
      <MoveItemModal
        item={makeItem({ name: "Special Jar" })}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    expect(screen.getByText(/Special Jar/)).toBeInTheDocument();
  });

  it("offers the storages as destinations", async () => {
    serveLocations(storageLocations);
    // One picker, one behaviour: the sheet moved from a native select to the
    // searchable one the product form uses, so the destinations
    // are behind a trigger rather than listed in the markup.
    render(
      <MoveItemModal
        item={makeItem()}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: /^Location/i }));
    expect(
      await screen.findByRole("button", { name: "Shelf B" }),
    ).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    render(
      <MoveItemModal
        item={makeItem()}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Move button is disabled when same storage is selected", () => {
    render(
      <MoveItemModal
        item={makeItem({ location_id: "loc-1" })}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    // The select defaults to loc-1 (same as item.location_id) → button disabled
    const buttons = screen.getAllByRole("button");
    const moveBtn = buttons.find(
      (b) =>
        b.textContent?.includes("Move") && b !== screen.getByLabelText("Close"),
    );
    expect(moveBtn).toBeDisabled();
  });
});

// ── ThresholdQuickSetSheet ────────────────────────────────────────────────────

describe("ThresholdQuickSetSheet", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
  });

  it("renders sheet with alert title", () => {
    render(<ThresholdQuickSetSheet item={makeItem()} onClose={onClose} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Minimum stock alert/i)).toBeInTheDocument();
  });

  it("renders item name", () => {
    render(
      <ThresholdQuickSetSheet
        item={makeItem({ name: "Milk" })}
        onClose={onClose}
      />,
    );
    expect(screen.getByText("Milk")).toBeInTheDocument();
  });

  it("renders number input with min_quantity value", () => {
    render(
      <ThresholdQuickSetSheet
        item={makeItem({ min_quantity: 3, quantity: "5" })}
        onClose={onClose}
      />,
    );
    const input = screen.getByRole<HTMLInputElement>("spinbutton");
    expect(input.value).toBe("3");
  });

  it("calls onClose when close button is clicked", () => {
    render(<ThresholdQuickSetSheet item={makeItem()} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows Remove button when item has threshold", () => {
    render(
      <ThresholdQuickSetSheet
        item={makeItem({ min_quantity: 2 })}
        onClose={onClose}
      />,
    );
    expect(screen.getByText("Remove")).toBeInTheDocument();
  });

  it("does not show Remove button when item has no threshold", () => {
    render(
      <ThresholdQuickSetSheet
        item={makeItem({ min_quantity: null })}
        onClose={onClose}
      />,
    );
    expect(screen.queryByText("Remove")).not.toBeInTheDocument();
  });
});

// ── CategoryCreateModal ───────────────────────────────────────────────────────

describe("CategoryCreateModal", () => {
  const onClose = vi.fn();
  const onSuccess = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
    onSuccess.mockClear();
  });

  it('renders the "New Category" heading', () => {
    render(<CategoryCreateModal onClose={onClose} onSuccess={onSuccess} />);
    expect(screen.getByText("New Category")).toBeInTheDocument();
  });

  it("renders name input", () => {
    render(<CategoryCreateModal onClose={onClose} onSuccess={onSuccess} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    render(<CategoryCreateModal onClose={onClose} onSuccess={onSuccess} />);
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ── CategoryFormModal ─────────────────────────────────────────────────────────

describe("CategoryFormModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
  });

  it('renders "Add New Category" title when creating', () => {
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={null}
        onClose={onClose}
      />,
    );
    expect(screen.getByText("Add New Category")).toBeInTheDocument();
  });

  it('renders "Edit Category" title when editing', () => {
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={makeCategory()}
        onClose={onClose}
      />,
    );
    expect(screen.getByText("Edit Category")).toBeInTheDocument();
  });

  it("pre-fills name input with editingCategory name", () => {
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={makeCategory({ name: "Dairy" })}
        onClose={onClose}
      />,
    );
    const input = screen.getByRole<HTMLInputElement>("textbox");
    expect(input.value).toBe("Dairy");
  });

  it("calls onClose when close button is clicked", () => {
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={null}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("returns null when not open and no editingCategory", () => {
    const { container } = render(
      <CategoryFormModal
        isOpen={false}
        editingCategory={null}
        onClose={onClose}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("does not draw the required star inside the appearance preview", () => {
    // The preview falls back to the name label while the field is empty, so
    // a star baked into "Category Name *" was rendered as part of the sample
    // the reader is judging the colour and symbol by.
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={null}
        onClose={onClose}
      />,
    );

    const preview = screen.getByText("Preview").closest("div")
      ?.parentElement as HTMLElement;
    expect(preview.textContent).not.toContain("*");
  });

  // ── Group field ──────────────────────────────────────────────────

  const mockMutations = () => {
    const createMutate = vi.fn();
    const updateMutate = vi.fn();
    vi.mocked(useCreateCategory).mockReturnValue({
      mutate: createMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useCreateCategory>);
    vi.mocked(useUpdateCategory).mockReturnValue({
      mutate: updateMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateCategory>);
    return { createMutate, updateMutate };
  };

  it("saving a category with a newly typed group sends group_label verbatim", async () => {
    const { createMutate } = mockMutations();
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={null}
        onClose={onClose}
      />,
    );

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Screwdrivers" },
    });

    fireEvent.click(screen.getByLabelText("Group"));
    fireEvent.change(
      screen.getByPlaceholderText(/search or type a new group/i),
      { target: { value: "Tools" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /create new group/i }));

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({ group_label: "Tools" }),
      expect.anything(),
    );
  });

  it("suggests groups the organisation already uses", () => {
    mockMutations();
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={null}
        onClose={onClose}
        groupSuggestions={["Tools", "Safety Gear"]}
      />,
    );

    fireEvent.click(screen.getByLabelText("Group"));

    expect(screen.getByText("Tools")).toBeInTheDocument();
    expect(screen.getByText("Safety Gear")).toBeInTheDocument();
  });

  it("offers a seeded group under the name the categories list gives it", () => {
    // The form built its options straight from the stored values, so a Polish
    // interface proposed "FREEZER", "FRIDGE" and "PANTRY" while the list two
    // clicks away called the same three things by their translations.
    mockMutations();
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={null}
        onClose={onClose}
        groupSuggestions={["FREEZER", "Safety Gear"]}
      />,
    );

    fireEvent.click(screen.getByLabelText("Group"));

    expect(screen.getByText("Freezer")).toBeInTheDocument();
    expect(screen.queryByText("FREEZER")).toBeNull();
    // A label the organisation typed is not a code and is left alone.
    expect(screen.getByText("Safety Gear")).toBeInTheDocument();
  });

  it("editing a category without a group does not send an empty string", () => {
    const { updateMutate } = mockMutations();
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={makeCategory({ group_label: null })}
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    const [call] = updateMutate.mock.calls;
    expect(call[0].data).not.toHaveProperty("group_label");
  });

  it("clearing an existing group sends an explicit null", () => {
    const { updateMutate } = mockMutations();
    render(
      <CategoryFormModal
        isOpen={true}
        editingCategory={makeCategory({ group_label: "Tools" })}
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByLabelText("Group"));
    fireEvent.click(screen.getByText("No group"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(updateMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "cat-1",
        data: expect.objectContaining({ group_label: null }),
      }),
      expect.anything(),
    );
  });
});
