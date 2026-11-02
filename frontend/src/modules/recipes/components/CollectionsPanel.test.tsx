import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  renderHook,
  screen,
  fireEvent,
  waitFor,
  within,
  act,
} from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { toast } from "sonner";
import i18n from "@/i18n/config";
import type { RecipeCollection } from "@/modules/recipes/types/core";
import {
  CollectionDialogs,
  CollectionsChips,
  CollectionsLoadFailed,
  CollectionsSidebar,
  useCollectionManager,
} from "./CollectionsPanel";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  useCreateRecipeCollection: () => ({ mutateAsync: mocks.create }),
  useUpdateRecipeCollection: () => ({ mutateAsync: mocks.update }),
  useDeleteRecipeCollection: () => ({ mutateAsync: mocks.remove }),
}));

const t = i18n.t.bind(i18n);

const leaf = (id: string, name: string): RecipeCollection => ({
  id,
  name,
  icon: null,
  parent_id: null,
  recipe_count: 0,
  children: [],
});

const week: RecipeCollection = {
  ...leaf("c1", "Week"),
  icon: "🍝",
  recipe_count: 4,
  children: [{ ...leaf("c2", "Monday"), parent_id: "c1" }],
};
const soups = leaf("c3", "Soups");

beforeEach(() => {
  vi.clearAllMocks();
  mocks.create.mockResolvedValue({});
  mocks.update.mockResolvedValue({});
  mocks.remove.mockResolvedValue({});
});

describe("useCollectionManager", () => {
  const setup = (activeCollectionId: string | null = null) => {
    const onSelect = vi.fn();
    const hook = renderHook(() =>
      useCollectionManager({ t, activeCollectionId, onSelect }),
    );
    return { ...hook, onSelect };
  };

  it("starts a create with an empty name, even after a rename left one behind", () => {
    const { result } = setup();
    act(() => result.current.openRename(week));
    expect(result.current.name).toBe("Week");
    act(() => result.current.openCreate());
    expect(result.current.name).toBe("");
    expect(result.current.modal).toEqual({ mode: "create" });
  });

  it("creates a collection under the trimmed name and closes the dialog", async () => {
    const { result } = setup();
    act(() => result.current.openCreate());
    act(() => result.current.setName("  Brunch  "));
    await act(() => result.current.handleSave());
    expect(mocks.create).toHaveBeenCalledWith({ name: "Brunch" });
    expect(toast.success).toHaveBeenCalledWith("Collection created");
    expect(result.current.modal).toBeNull();
  });

  it("renames the collection that was opened, not a new one", async () => {
    const { result } = setup();
    act(() => result.current.openRename(week));
    act(() => result.current.setName("Weekdays"));
    await act(() => result.current.handleSave());
    expect(mocks.update).toHaveBeenCalledWith({
      id: "c1",
      data: { name: "Weekdays" },
    });
    expect(mocks.create).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Collection updated");
  });

  it("saves nothing for a blank name", async () => {
    const { result } = setup();
    act(() => result.current.openCreate());
    act(() => result.current.setName("   "));
    await act(() => result.current.handleSave());
    expect(mocks.create).not.toHaveBeenCalled();
    expect(result.current.modal).toEqual({ mode: "create" });
  });

  it("keeps the dialog open and says why when the save is refused", async () => {
    mocks.create.mockRejectedValue(new Error("boom"));
    const { result } = setup();
    act(() => result.current.openCreate());
    act(() => result.current.setName("Brunch"));
    await act(() => result.current.handleSave());
    expect(toast.error).toHaveBeenCalled();
    expect(result.current.modal).toEqual({ mode: "create" });
  });

  it("deselects the collection it deletes when that one was the active filter", async () => {
    const { result, onSelect } = setup("c1");
    act(() => result.current.setDeleteTarget(week));
    await act(() => result.current.handleDelete());
    expect(mocks.remove).toHaveBeenCalledWith("c1");
    expect(onSelect).toHaveBeenCalledWith(null);
    expect(toast.success).toHaveBeenCalledWith("Collection deleted");
    expect(result.current.deleteTarget).toBeNull();
  });

  it("leaves the filter alone when another collection is deleted", async () => {
    const { result, onSelect } = setup("c3");
    act(() => result.current.setDeleteTarget(week));
    await act(() => result.current.handleDelete());
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("keeps the delete confirmation open when the delete fails", async () => {
    mocks.remove.mockRejectedValue(new Error("boom"));
    const { result } = setup();
    act(() => result.current.setDeleteTarget(week));
    await act(() => result.current.handleDelete());
    expect(toast.error).toHaveBeenCalled();
    expect(result.current.deleteTarget).toEqual(week);
  });

  it("does nothing when asked to delete with no target", async () => {
    const { result } = setup();
    await act(() => result.current.handleDelete());
    expect(mocks.remove).not.toHaveBeenCalled();
  });
});

describe("CollectionsChips", () => {
  const renderChips = (
    props: Partial<Parameters<typeof CollectionsChips>[0]>,
  ) => {
    const onSelect = vi.fn();
    const onOpenCreate = vi.fn();
    render(
      <CollectionsChips
        collections={[week, soups]}
        activeCollectionId={null}
        onSelect={onSelect}
        onOpenCreate={onOpenCreate}
        t={t}
        {...props}
      />,
    );
    return { onSelect, onOpenCreate };
  };

  it("renders nothing while there are no collections to filter by", () => {
    renderChips({ collections: [] });
    expect(screen.queryByTestId("collections-chips")).not.toBeInTheDocument();
  });

  it("selects a collection, and clears the filter from 'All recipes'", () => {
    const { onSelect } = renderChips({});
    fireEvent.click(screen.getByRole("button", { name: "Soups" }));
    expect(onSelect).toHaveBeenLastCalledWith("c3");
    fireEvent.click(screen.getByRole("button", { name: "All recipes" }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("offers creating one, unless the reader may not write", () => {
    const { onOpenCreate } = renderChips({});
    fireEvent.click(screen.getByRole("button", { name: /New collection/ }));
    expect(onOpenCreate).toHaveBeenCalledTimes(1);
  });

  it("hides the create chip from a reader", () => {
    renderChips({ canWrite: false });
    expect(
      screen.queryByRole("button", { name: /New collection/ }),
    ).not.toBeInTheDocument();
  });
});

describe("CollectionsSidebar", () => {
  const manager = () => ({
    modal: null,
    deleteTarget: null,
    name: "",
    openCreate: vi.fn(),
    openRename: vi.fn(),
    handleSave: vi.fn(),
    handleDelete: vi.fn(),
    setDeleteTarget: vi.fn(),
    setName: vi.fn(),
    closeModal: vi.fn(),
  });

  const renderSidebar = (
    props: Partial<Parameters<typeof CollectionsSidebar>[0]> = {},
  ) => {
    const onSelect = vi.fn();
    const m = manager();
    render(
      <DndContext>
        <CollectionsSidebar
          collections={[week, soups]}
          activeCollectionId={null}
          isOverCollection={false}
          onSelect={onSelect}
          manager={m}
          t={t}
          {...props}
        />
      </DndContext>,
    );
    return { onSelect, m };
  };

  it("renders nothing while there are no collections", () => {
    renderSidebar({ collections: [] });
    expect(screen.queryByTestId("collections-sidebar")).not.toBeInTheDocument();
  });

  it("lists nested collections and the recipe count of the ones that hold some", () => {
    renderSidebar();
    const sidebar = screen.getByTestId("collections-sidebar");
    expect(within(sidebar).getByText("Monday")).toBeInTheDocument();
    expect(within(sidebar).getByText("4")).toBeInTheDocument();
  });

  it("selects by click and by Enter or Space, but not by other keys", () => {
    const { onSelect } = renderSidebar();
    const row = screen.getByText("Soups").closest('[role="button"]')!;
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(row, { key: "Enter" });
    fireEvent.keyDown(row, { key: " " });
    expect(onSelect).toHaveBeenCalledTimes(3);
    fireEvent.keyDown(row, { key: "a" });
    expect(onSelect).toHaveBeenCalledTimes(3);
  });

  it("renames and deletes without also selecting the row", () => {
    const { onSelect, m } = renderSidebar();
    fireEvent.click(screen.getAllByRole("button", { name: "Rename" })[0]);
    expect(m.openRename).toHaveBeenCalledWith(week);
    fireEvent.click(
      screen.getAllByRole("button", { name: "Delete collection" })[0],
    );
    expect(m.setDeleteTarget).toHaveBeenCalledWith(week);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("opens the create dialog from its own button", () => {
    const { m } = renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "New collection" }));
    expect(m.openCreate).toHaveBeenCalledTimes(1);
  });

  it("offers a reader no rename, delete or create", () => {
    renderSidebar({ canWrite: false });
    expect(
      screen.queryByRole("button", { name: "Rename" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete collection" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New collection" }),
    ).not.toBeInTheDocument();
  });
});

describe("CollectionDialogs", () => {
  const base = () => ({
    modal: null as {
      mode: "create" | "rename";
      collection?: RecipeCollection;
    } | null,
    deleteTarget: null as RecipeCollection | null,
    name: "",
    openCreate: vi.fn(),
    openRename: vi.fn(),
    handleSave: vi.fn().mockResolvedValue(undefined),
    handleDelete: vi.fn().mockResolvedValue(undefined),
    setDeleteTarget: vi.fn(),
    setName: vi.fn(),
    closeModal: vi.fn(),
  });

  it("types into the name field, saves on Enter and on the Save button", () => {
    const m = { ...base(), modal: { mode: "create" as const }, name: "Brunch" };
    render(<CollectionDialogs manager={m} t={t} />);
    const input = screen.getByLabelText("Collection name");
    fireEvent.change(input, { target: { value: "Dinner" } });
    expect(m.setName).toHaveBeenCalledWith("Dinner");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(m.handleSave).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(m.handleSave).toHaveBeenCalledTimes(2);
  });

  it("disables Save while the name is blank and closes on Cancel", () => {
    const m = { ...base(), modal: { mode: "create" as const }, name: "  " };
    render(<CollectionDialogs manager={m} t={t} />);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(m.closeModal).toHaveBeenCalledTimes(1);
  });

  it("titles the dialog for a rename", () => {
    const m = {
      ...base(),
      modal: { mode: "rename" as const, collection: week },
      name: "Week",
    };
    render(<CollectionDialogs manager={m} t={t} />);
    expect(screen.getByRole("dialog", { name: "Rename" })).toBeInTheDocument();
  });

  it("names the collection in the delete confirmation and confirms or cancels it", async () => {
    const m = { ...base(), deleteTarget: week };
    render(<CollectionDialogs manager={m} t={t} />);
    expect(screen.getByText(/Delete collection "Week"\?/)).toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: "Delete collection" }).pop()!,
    );
    await waitFor(() => expect(m.handleDelete).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(m.setDeleteTarget).toHaveBeenCalledWith(null);
  });
});

describe("CollectionsLoadFailed", () => {
  it("says nothing while the read worked", () => {
    const { container } = render(
      <CollectionsLoadFailed failed={false} onRetry={vi.fn()} t={t} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("says the strip is missing and retries on request", () => {
    const onRetry = vi.fn();
    render(<CollectionsLoadFailed failed onRetry={onRetry} t={t} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Collections could not be loaded.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
