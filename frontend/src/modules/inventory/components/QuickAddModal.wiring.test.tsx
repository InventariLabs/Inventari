import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Item } from "@/types";
import { useQuickAdd } from "@/modules/inventory/hooks/useQuickAdd";
import QuickAddModal from "./QuickAddModal";

const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  setActiveTab: vi.fn(),
  handleInputChange: vi.fn(),
  hookOnSuccess: null as ((item: Item) => void) | null,
}));

vi.mock("@/modules/inventory/hooks/useQuickAdd", () => ({
  useQuickAdd: vi.fn(),
}));

vi.mock("./quick-add/VisionTab", () => ({
  VisionTab: ({ onEnterManually }: { onEnterManually: () => void }) => (
    <button onClick={onEnterManually}>type it in instead</button>
  ),
}));

vi.mock("./quick-add/ManualTab", () => ({
  ManualTab: ({ onAddCategory }: { onAddCategory: () => void }) => (
    <button onClick={onAddCategory}>new category</button>
  ),
}));

vi.mock("./CategoryCreateModal", () => ({
  default: ({
    onClose,
    onSuccess,
  }: {
    onClose: () => void;
    onSuccess: (cat: { id: string }) => void;
  }) => (
    <div role="dialog" aria-label="category create">
      <button onClick={onClose}>close category</button>
      <button onClick={() => onSuccess({ id: "cat-new" })}>
        create category
      </button>
    </div>
  ),
}));

vi.mock("./AttachLabelToItemSheet", () => ({
  AttachLabelToItemSheet: ({
    onClose,
    onAttached,
  }: {
    onClose: () => void;
    onAttached: () => void;
  }) => (
    <div role="dialog" aria-label="attach">
      <button onClick={onClose}>close attach</button>
      <button onClick={onAttached}>attached</button>
    </div>
  ),
}));

function hookState(over: Partial<ReturnType<typeof useQuickAdd>> = {}) {
  vi.mocked(useQuickAdd).mockImplementation((options) => {
    mocks.hookOnSuccess = options.onSuccess;
    return {
      activeTab: "manual",
      setActiveTab: mocks.setActiveTab,
      visionEnabled: true,
      formData: { name: "Jam", location_id: "loc-1" },
      errors: {},
      fieldDefinitions: [],
      handleInputChange: mocks.handleInputChange,
      submit: mocks.submit,
      isAnalyzing: false,
      imagePreview: null,
      setImagePreview: vi.fn(),
      handleVisionAI: vi.fn(),
      noStorages: false,
      hasHiddenStorages: false,
      carriedOver: { storage: false, category: false },
      clearCarriedOver: vi.fn(),
      categories: [],
      templateUnit: null,
      pendingUnitChoice: null,
      resolveUnitChoice: vi.fn(),
      assignMutation: { isPending: false },
      handleFileSelect: vi.fn(),
      handleImageSelect: vi.fn(),
      ...over,
    } as unknown as ReturnType<typeof useQuickAdd>;
  });
}

function open(props: Partial<Parameters<typeof QuickAddModal>[0]> = {}) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(<QuickAddModal onClose={onClose} onSuccess={onSuccess} {...props} />);
  return { onClose, onSuccess };
}

/**
 * The modal around the quick-add form: the save button submits, a saved
 * product closes the sheet and reaches the caller, the tabs switch, a new
 * category lands in the form, an attached label closes everything, and the
 * no-location guard opens the place to fix it in a new tab. Each of these is
 * a click that would otherwise do nothing or lose the form.
 */
describe("QuickAddModal — what its buttons and children do", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hookState();
  });

  afterEach(() => vi.restoreAllMocks());

  it("submits from the footer and closes once the product is saved", async () => {
    const user = userEvent.setup();
    const { onClose, onSuccess } = open();

    await user.click(screen.getByRole("button", { name: "Add Product" }));
    expect(mocks.submit).toHaveBeenCalledTimes(1);

    const saved = { id: "item-1" } as Item;
    mocks.hookOnSuccess?.(saved);
    expect(onSuccess).toHaveBeenCalledWith(saved);
    expect(onClose).toHaveBeenCalled();
  });

  it("switches to the camera tab and back from it", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("button", { name: /vision ai/i }));
    expect(mocks.setActiveTab).toHaveBeenLastCalledWith("vision");

    hookState({ activeTab: "vision" });
    const { unmount } = render(
      <QuickAddModal onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    await user.click(
      screen.getByRole("button", { name: "type it in instead" }),
    );
    expect(mocks.setActiveTab).toHaveBeenLastCalledWith("manual");
    unmount();
  });

  it("puts a category created on the way into the form", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("button", { name: "new category" }));
    await user.click(screen.getByRole("button", { name: "create category" }));

    expect(mocks.handleInputChange).toHaveBeenCalledWith(
      "category_id",
      "cat-new",
    );
    expect(
      screen.queryByRole("dialog", { name: "category create" }),
    ).toBeNull();

    await user.click(screen.getByRole("button", { name: "new category" }));
    await user.click(screen.getByRole("button", { name: "close category" }));
    expect(
      screen.queryByRole("dialog", { name: "category create" }),
    ).toBeNull();
  });

  it("closes everything once a free label was attached to an existing product", async () => {
    const user = userEvent.setup();
    const { onClose } = open({
      labelCode: "INV-ABC123",
      messageKey: "scan:result.labelReady",
    });

    await user.click(
      screen.getByRole("button", { name: "Attach to an existing product" }),
    );
    await user.click(screen.getByRole("button", { name: "close attach" }));
    expect(screen.queryByRole("dialog", { name: "attach" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Attach to an existing product" }),
    );
    await user.click(screen.getByRole("button", { name: "attached" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("opens the locations in a new tab when there is nowhere to put the product", async () => {
    hookState({ noStorages: true });
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const user = userEvent.setup();
    open();

    await user.click(
      screen.getByRole("button", { name: "Configure locations" }),
    );
    expect(opened).toHaveBeenCalledWith(
      "/inventory/locations",
      "_blank",
      "noopener",
    );
  });

  it("opens the module-data switch when the locations are only hidden", async () => {
    hookState({ noStorages: true, hasHiddenStorages: true });
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("button", { name: "Open settings" }));
    expect(opened).toHaveBeenCalledWith(
      "/settings#module-data",
      "_blank",
      "noopener",
    );
  });
});
