import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { toast } from "sonner";
import { MemoryRouter } from "react-router-dom";
import type { Item } from "@/types";

type MutateOptions = {
  onSuccess?: (result: unknown) => void;
  onError?: (error: unknown) => void;
};

const mocks = vi.hoisted(() => ({
  deleteMutate: vi.fn(),
  consumeMutate: vi.fn(),
  consumeMutateAsync: vi.fn(),
  discardMutate: vi.fn(),
  discardMutateAsync: vi.fn(),
  quantityMutate: vi.fn(),
  exportXlsx: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("./useItemMutations", () => ({
  useDeleteItem: () => ({
    mutate: mocks.deleteMutate,
    mutateAsync: vi.fn(),
    isPending: false,
    variables: undefined,
  }),
  useConsumeItem: () => ({
    mutate: mocks.consumeMutate,
    mutateAsync: mocks.consumeMutateAsync,
    isPending: false,
    variables: undefined,
  }),
  useDiscardItem: () => ({
    mutate: mocks.discardMutate,
    mutateAsync: mocks.discardMutateAsync,
    isPending: false,
    variables: undefined,
  }),
  useUpdateItemQuantity: () => ({
    mutate: mocks.quantityMutate,
    mutateAsync: vi.fn(),
    isPending: false,
    variables: undefined,
  }),
}));

vi.mock("@/lib/api/items", () => ({
  itemsApi: { exportXlsx: mocks.exportXlsx },
}));

vi.mock("@/utils/helpers", async () => {
  const actual =
    await vi.importActual<typeof import("@/utils/helpers")>("@/utils/helpers");
  return { ...actual, downloadBlob: mocks.downloadBlob };
});

import { useItemsPageActions } from "./useItemsPageActions";

const flour = { id: "item-1", name: "Flour", quantity: "2" } as unknown as Item;

function renderActions(
  over: Partial<Parameters<typeof useItemsPageActions>[0]> = {},
) {
  const setConsumeDialogItem = vi.fn();
  const setDeleteReasonItem = vi.fn();
  const view = renderHook(
    () =>
      useItemsPageActions({
        items: [flour],
        storageFilter: "",
        exportParams: { search: "fl" },
        setConsumeDialogItem,
        setDeleteReasonItem,
        ...over,
      }),
    {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <MemoryRouter>{children}</MemoryRouter>
      ),
    },
  );
  return { ...view, setConsumeDialogItem, setDeleteReasonItem };
}

function lastOptions(mock: ReturnType<typeof vi.fn>): MutateOptions {
  return mock.mock.calls.at(-1)?.[1] as MutateOptions;
}

/**
 * The page's row handlers: a consume or delete that opens the wrong dialog
 * (or none), "+1" sending the old quantity, a failed remove with no message,
 * or an export that never downloads or names the file after the wrong
 * location — each is a click that looks dead or lies to the reader.
 */
describe("useItemsPageActions — row handlers, failures and the export", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(toast, "success").mockImplementation(() => "");
    vi.spyOn(toast, "error").mockImplementation(() => "");
    vi.spyOn(toast, "loading").mockImplementation(() => "");
  });

  it("opens the consume and delete dialogs on the row's own item, and ignores an unknown id", () => {
    const { result, setConsumeDialogItem, setDeleteReasonItem } =
      renderActions();

    result.current.handleConsume("item-1");
    result.current.handleDelete("item-1");
    result.current.handleConsume("missing");
    result.current.handleDelete("missing");

    expect(setConsumeDialogItem).toHaveBeenCalledTimes(1);
    expect(setConsumeDialogItem).toHaveBeenCalledWith(flour);
    expect(setDeleteReasonItem).toHaveBeenCalledTimes(1);
    expect(setDeleteReasonItem).toHaveBeenCalledWith(flour);
  });

  it("toasts the delete only once it succeeded", () => {
    const { result } = renderActions();
    result.current.deleteMutation.mutate("item-1", "DAMAGED", "dropped");

    expect(mocks.deleteMutate).toHaveBeenCalledWith(
      { itemId: "item-1", reason: "DAMAGED", notes: "dropped" },
      expect.any(Object),
    );
    expect(toast.success).not.toHaveBeenCalled();
    lastOptions(mocks.deleteMutate).onSuccess?.({});
    expect(toast.success).toHaveBeenCalledWith("Product deleted");
  });

  it("names a failed consume and a failed discard differently", () => {
    const { result } = renderActions();

    result.current.consumeMutation.mutate("item-1", 1, "USED");
    lastOptions(mocks.consumeMutate).onError?.(new Error("x"));
    expect(toast.error).toHaveBeenLastCalledWith("Failed to remove the unit");

    result.current.consumeMutation.mutate("item-1", 1, "EXPIRED");
    expect(mocks.discardMutate).toHaveBeenCalledWith(
      { itemId: "item-1", quantity: 1, reason: "EXPIRED", notes: undefined },
      expect.any(Object),
    );
    lastOptions(mocks.discardMutate).onError?.(new Error("x"));
    expect(toast.error).toHaveBeenLastCalledWith("Failed to remove from stock");
  });

  it("awaits the consume and reports what is left", async () => {
    mocks.consumeMutateAsync.mockResolvedValue({
      id: "item-1",
      quantity: "1",
      is_deleted: false,
    });
    const { result } = renderActions();

    await act(() => result.current.consumeMutation.mutateAsync("item-1"));

    expect(mocks.consumeMutateAsync).toHaveBeenCalledWith({
      itemId: "item-1",
      quantity: 1,
      reason: "USED",
      notes: undefined,
    });
    expect(toast.success).toHaveBeenCalledWith("Removed 1 unit — 1 left");
  });

  it("awaits a consume of the last unit with the way back to the record", async () => {
    mocks.consumeMutateAsync.mockResolvedValue({
      id: "item-1",
      quantity: "0",
      is_deleted: false,
    });
    const { result } = renderActions();

    await act(() => result.current.consumeMutation.mutateAsync("item-1"));

    const [, options] = vi.mocked(toast.success).mock.calls[0] as unknown as [
      string,
      { action?: { label: string } },
    ];
    expect(options?.action?.label).toBe("Open record");
  });

  it("adds one unit on top of the row's quantity", () => {
    const { result } = renderActions();

    result.current.handleAddOne("item-1");
    result.current.handleAddOne("missing");

    expect(mocks.quantityMutate).toHaveBeenCalledTimes(1);
    expect(mocks.quantityMutate).toHaveBeenCalledWith(
      { itemId: "item-1", quantity: 3 },
      expect.any(Object),
    );
    lastOptions(mocks.quantityMutate).onSuccess?.({ quantity: "3" });
    expect(toast.success).toHaveBeenCalledWith("Added 1 unit — 3 in stock");
  });

  it("exports the list's own rows into a file named after the filtered location", async () => {
    const blob = new Blob(["x"]);
    mocks.exportXlsx.mockResolvedValue(blob);
    const { result } = renderActions({
      storageFilter: "loc-1",
      storages: [{ id: "loc-1", name: "Dry Pantry" }] as unknown as Parameters<
        typeof useItemsPageActions
      >[0]["storages"],
    });

    await act(() => result.current.handleExport());

    expect(mocks.exportXlsx).toHaveBeenCalledWith({ search: "fl" });
    const [sentBlob, filename] = mocks.downloadBlob.mock.calls[0] as [
      Blob,
      string,
    ];
    expect(sentBlob).toBe(blob);
    expect(filename).toMatch(/^inventory_dry_pantry_.+\.xlsx$/);
    expect(toast.success).toHaveBeenCalledWith("Export complete", {
      id: "items-export",
    });
  });

  it("reports a failed export instead of downloading", async () => {
    mocks.exportXlsx.mockRejectedValue(new Error("boom"));
    const { result } = renderActions();

    await act(() => result.current.handleExport());

    expect(mocks.downloadBlob).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(expect.any(String), {
      id: "items-export",
    });
  });
});
