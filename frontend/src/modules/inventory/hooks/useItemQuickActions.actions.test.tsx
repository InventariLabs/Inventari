import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { signInWith, signOut } from "@/test/auth";
import type { Item } from "@/types";

type MutateOptions = {
  onSuccess?: (result: unknown) => void;
  onError?: (error: unknown) => void;
};

const mocks = vi.hoisted(() => ({
  consumeMutate: vi.fn(),
  quantityMutate: vi.fn(),
  deleteMutateAsync: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/utils/logger", () => ({
  logger: { error: vi.fn(), warn: vi.fn(), debug: vi.fn(), info: vi.fn() },
}));

vi.mock("./useItemMutations", () => ({
  useConsumeItem: () => ({ mutate: mocks.consumeMutate, isPending: false }),
  useUpdateItemQuantity: () => ({
    mutate: mocks.quantityMutate,
    isPending: false,
  }),
  useDeleteItem: () => ({
    mutateAsync: mocks.deleteMutateAsync,
    isPending: false,
  }),
}));

import { useItemQuickActions } from "./useItemQuickActions";

function item(over: Partial<Item> = {}): Item {
  return {
    id: "item-1",
    name: "Rice",
    quantity: "2",
    uom: null,
    category: null,
    ...over,
  } as unknown as Item;
}

function lastOptions(mock: ReturnType<typeof vi.fn>): MutateOptions {
  return mock.mock.calls.at(-1)?.[1] as MutateOptions;
}

function render(
  record: Item,
  opts: { onDeleted?: () => void; inVirtualPlace?: boolean } = {},
) {
  const onDone = vi.fn();
  const onMove = vi.fn();
  const view = renderHook(() =>
    useItemQuickActions(record, { onDone, onMove, ...opts }),
  );
  const action = (id: string) =>
    view.result.current.actions.find((a) => a.id === id);
  return { ...view, onDone, onMove, action };
}

/**
 * The quick actions shared by the list's sheet and the product page: what
 * each one is offered on, what it sends, what it says on success and on
 * failure, and that the delete dialog closes only on a delete that happened.
 * A wrong permission check offers erasing to a reader who may only top up; a
 * dropped onError leaves a failed click silent.
 */
describe("useItemQuickActions — offers, results and the delete dialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["items:read", "items:write", "items:delete"]);
  });

  afterEach(() => signOut());

  it("offers nothing to a read-only account", () => {
    signInWith(["items:read"]);
    const { result } = render(item());
    expect(result.current.actions).toEqual([]);
  });

  it("offers consume, +1, move and delete on a product, delete only with items:delete", () => {
    const { result } = render(item());
    expect(result.current.actions.map((a) => a.id)).toEqual([
      "consume",
      "add_one",
      "move",
      "discard",
    ]);
    expect(result.current.vocabularyNote).toBeNull();

    signInWith(["items:read", "items:write"]);
    const { result: withoutDelete } = render(item());
    expect(withoutDelete.current.actions.map((a) => a.id)).not.toContain(
      "discard",
    );
  });

  it("speaks an asset's vocabulary and offers no consume on equipment", () => {
    const { result } = render(
      item({
        category: { context_tag: "equipment" },
      } as unknown as Partial<Item>),
    );
    expect(result.current.actions.map((a) => a.id)).toEqual([
      "add_one",
      "move",
      "discard",
    ]);
    expect(result.current.vocabularyNote).toEqual(expect.any(String));
  });

  it("keeps the note about the actions from an account offered none", () => {
    signInWith(["items:read"]);
    const { result } = render(
      item({
        category: { context_tag: "equipment" },
      } as unknown as Partial<Item>),
    );
    expect(result.current.actions).toEqual([]);
    expect(result.current.vocabularyNote).toBeNull();
  });

  it("disables consume on an empty record", () => {
    const { action } = render(item({ quantity: "0" }));
    expect(action("consume")?.disabled).toBe(true);
  });

  it("says a consume used the record up, or what is left", () => {
    const { action, onDone } = render(item());
    act(() => action("consume")!.onClick());
    lastOptions(mocks.consumeMutate).onSuccess?.({ quantity: "0" });
    expect(toast.success).toHaveBeenLastCalledWith("Product has been used up");

    lastOptions(mocks.consumeMutate).onSuccess?.({ quantity: "1" });
    expect(toast.success).toHaveBeenLastCalledWith("Removed 1 unit — 1 left");
    expect(onDone).toHaveBeenCalledTimes(2);
  });

  it("reports a failed consume", () => {
    const { action, onDone } = render(item());
    act(() => action("consume")!.onClick());
    lastOptions(mocks.consumeMutate).onError?.(new Error("x"));
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith("Failed to remove the unit");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("adds one unit to the record's quantity and reports the new total", () => {
    const { action, onDone } = render(item());
    act(() => action("add_one")!.onClick());
    expect(mocks.quantityMutate).toHaveBeenCalledWith(
      { itemId: "item-1", quantity: 3 },
      expect.any(Object),
    );
    lastOptions(mocks.quantityMutate).onSuccess?.({ quantity: "3" });
    expect(toast.success).toHaveBeenCalledWith("Product added — 3 in total");
    expect(onDone).toHaveBeenCalled();

    lastOptions(mocks.quantityMutate).onError?.(new Error("x"));
    expect(toast.error).toHaveBeenCalledTimes(1);
    // The unit, not the shopping list: this button adds to stock.
    expect(toast.error).toHaveBeenCalledWith("Failed to add the unit");
  });

  it("hands the move to the caller", () => {
    const { action, onMove } = render(item());
    action("move")!.onClick();
    expect(onMove).toHaveBeenCalled();
  });

  it("opens the delete dialog, deletes with the reason and leaves through onDeleted", async () => {
    mocks.deleteMutateAsync.mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    const { result, action, onDone } = render(item(), { onDeleted });

    act(() => action("discard")!.onClick());
    expect(result.current.deleteDialog.open).toBe(true);

    await act(() => result.current.deleteDialog.onConfirm("DAMAGED", "torn"));

    expect(mocks.deleteMutateAsync).toHaveBeenCalledWith({
      itemId: "item-1",
      reason: "DAMAGED",
      notes: "torn",
    });
    expect(result.current.deleteDialog.open).toBe(false);
    expect(toast.success).toHaveBeenCalledWith("Product deleted");
    expect(onDeleted).toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("keeps the delete dialog open when the delete fails", async () => {
    mocks.deleteMutateAsync.mockRejectedValue(new Error("nope"));
    const { result, action } = render(item());

    act(() => action("discard")!.onClick());
    await act(async () => {
      await expect(
        result.current.deleteDialog.onConfirm("DAMAGED", ""),
      ).rejects.toThrow("nope");
    });

    expect(result.current.deleteDialog.open).toBe(true);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("closes the delete dialog on cancel", () => {
    const { result, action } = render(item());
    act(() => action("discard")!.onClick());
    act(() => result.current.deleteDialog.onCancel());
    expect(result.current.deleteDialog.open).toBe(false);
  });

  describe("a record in a system place", () => {
    it("offers no unit the server would refuse, and keeps the way back", () => {
      const { action } = render(item({ quantity: "0" }), {
        inVirtualPlace: true,
      });

      expect(action("add_one")).toBeUndefined();
      expect(action("move")).toBeDefined();
    });

    it("offers the unit on a real shelf, even at zero", () => {
      const { action } = render(item({ quantity: "0" }));

      expect(action("add_one")).toBeDefined();
    });
  });
});
