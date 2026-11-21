import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  type MockInstance,
} from "vitest";
import { act, renderHook } from "@testing-library/react";
import i18next from "i18next";
import { toast } from "sonner";
import { MemoryRouter } from "react-router-dom";
import { withLanguage } from "@/test/mocks/i18n";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  deleteMutate: vi.fn(),
  deleteMutateAsync: vi.fn(),
  consumeOptions: null as {
    onSuccess: (item: unknown) => void;
    onError: (error: unknown) => void;
  } | null,
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("./useItemMutations", () => ({
  useConsumeItem: () => ({
    mutate: (
      _vars: unknown,
      options: {
        onSuccess: (item: unknown) => void;
        onError: (e: unknown) => void;
      },
    ) => {
      mocks.consumeOptions = options;
    },
    mutateAsync: vi.fn(),
    isPending: false,
    variables: null,
  }),
  useDeleteItem: () => ({
    mutate: mocks.deleteMutate,
    mutateAsync: mocks.deleteMutateAsync,
    isPending: false,
    variables: null,
  }),
  useDiscardItem: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    variables: null,
  }),
  useUpdateItemQuantity: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    variables: null,
  }),
}));

import { useItemsPageActions } from "./useItemsPageActions";

type ToastOptions = {
  description?: string;
  action?: { label: string; onClick: () => void };
};

const setBulkDeleteIds = vi.fn();

function renderActions() {
  return renderHook(
    () =>
      useItemsPageActions({
        items: [],
        storageFilter: "",
        exportParams: {},
        setConsumeDialogItem: vi.fn(),
        setDeleteReasonItem: vi.fn(),
        setBulkDeleteIds,
      }),
    {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <MemoryRouter>{children}</MemoryRouter>
      ),
    },
  );
}

describe("useItemsPageActions — the used-up toast leads back to the record", () => {
  let toastSuccess: MockInstance;

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.consumeOptions = null;
    toastSuccess = vi.spyOn(toast, "success").mockImplementation(() => "");
  });

  it("says the record left the list and opens it, when the last unit went", () => {
    const { result } = renderActions();
    result.current.consumeMutation.mutate("item-9");

    mocks.consumeOptions?.onSuccess({
      id: "item-9",
      quantity: 0,
      is_deleted: false,
    });

    expect(toastSuccess).toHaveBeenCalledTimes(1);
    const [message, options] = toastSuccess.mock.calls[0] as unknown as [
      string,
      ToastOptions | undefined,
    ];
    expect(message).toBe("Product has been used up");
    expect(options?.description).toBe("The record left the products list.");
    expect(options?.action?.label).toBe("Open record");
    options?.action?.onClick();
    expect(mocks.navigate).toHaveBeenCalledWith("/inventory/items/item-9");
  });

  it("keeps the plain confirmation for a record that still has stock", () => {
    const { result } = renderActions();
    result.current.consumeMutation.mutate("item-9");

    mocks.consumeOptions?.onSuccess({
      id: "item-9",
      quantity: 4,
      uom: { symbol: "pcs" },
      is_deleted: false,
    });

    expect(toastSuccess).toHaveBeenCalledTimes(1);
    const [message, options] = toastSuccess.mock.calls[0] as unknown as [
      string,
      ToastOptions | undefined,
    ];
    // One catalogue key, not a sentence glued from parts: a glued English word
    // and a raw symbol would leave a translated message half in English.
    expect(String(message)).toBe(
      i18next.t("items:quickActions.consumedSuccessRemaining", {
        removed: "1 pcs.",
        remaining: "4 pcs.",
      }),
    );
    expect(options?.description).toBeUndefined();
    expect(options?.action).toBeUndefined();
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("confirms the amount that was removed, not a single unit", () => {
    const { result } = renderActions();
    result.current.consumeMutation.mutate("item-9", 5);

    mocks.consumeOptions?.onSuccess({
      id: "item-9",
      quantity: 20,
      uom: { symbol: "pcs" },
      is_deleted: false,
    });

    const [message] = toastSuccess.mock.calls[0] as unknown as [string];
    expect(String(message)).toContain("Removed 5 pcs.");
    expect(String(message)).toContain("20 pcs. left");
    expect(String(message)).not.toContain("1 unit");
  });

  it("names the unit the way the interface names it", async () => {
    await withLanguage("pl", () => {
      const { result } = renderActions();
      result.current.consumeMutation.mutate("item-9");

      mocks.consumeOptions?.onSuccess({
        id: "item-9",
        quantity: 8,
        uom: { symbol: "pcs" },
        is_deleted: false,
      });

      const [message] = toastSuccess.mock.calls[0] as unknown as [string];
      // "szt.", not "pcs": the reader of the Polish interface is told what
      // is left in the unit the rest of the list uses.
      expect(String(message)).toContain("8 szt.");
      expect(String(message)).not.toContain("pcs");
    });
  });

  it("does not navigate for a record the consume actually deleted", () => {
    // is_deleted is the archive path, not the consumed shelf — the detail
    // route would answer for a record that is no longer there.
    const { result } = renderActions();
    result.current.consumeMutation.mutate("item-9");

    mocks.consumeOptions?.onSuccess({
      id: "item-9",
      quantity: 0,
      is_deleted: true,
    });

    expect(toastSuccess).toHaveBeenCalledTimes(1);
    const [, options] = toastSuccess.mock.calls[0] as unknown as [
      string,
      ToastOptions | undefined,
    ];
    expect(options?.action).toBeUndefined();
    expect(mocks.navigate).not.toHaveBeenCalled();
  });
});

describe("useItemsPageActions — a swipe carries no reason, a bulk delete asks once", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("swipes straight to the delete without naming a reason", () => {
    // The five-second Undo window is the confirmation on this door, so it
    // deletes at once and never opens the reason dialog.
    const { result } = renderActions();

    result.current.handleSwipeDelete("item-1");

    expect(mocks.deleteMutate).toHaveBeenCalledTimes(1);
    const [variables] = mocks.deleteMutate.mock.calls[0] as [
      { itemId: string; reason?: string; notes?: string },
    ];
    expect(variables.reason).toBeUndefined();
    expect(variables.itemId).toBe("item-1");
  });

  it("hands a selection to the reason dialog instead of deleting it", () => {
    const { result } = renderActions();

    act(() => {
      result.current.handleBulkDelete(["item-1", "item-2"]);
    });

    expect(setBulkDeleteIds).toHaveBeenCalledWith(["item-1", "item-2"]);
    expect(mocks.deleteMutateAsync).not.toHaveBeenCalled();
  });

  it("opens nothing for an empty selection", () => {
    const { result } = renderActions();

    act(() => {
      result.current.handleBulkDelete([]);
    });

    expect(setBulkDeleteIds).not.toHaveBeenCalled();
  });

  it("deletes every row of the batch with the one reason it was given", async () => {
    const toastSuccess = vi
      .spyOn(toast, "success")
      .mockImplementation(() => "");
    const { result } = renderActions();

    await act(async () => {
      await result.current.confirmBulkDelete(
        ["item-1", "item-2"],
        "EXPIRED",
        "",
      );
    });

    const variables = mocks.deleteMutateAsync.mock.calls.map(
      (call: unknown[]) => (call as [unknown])[0],
    );
    expect(variables).toEqual([
      { itemId: "item-1", reason: "EXPIRED", notes: undefined },
      { itemId: "item-2", reason: "EXPIRED", notes: undefined },
    ]);
    // A bulk delete names the count, not one product's word for a whole selection.
    expect(toastSuccess).toHaveBeenCalledWith("2 products deleted");
  });

  it("hands a refused bulk delete back to the dialog that asked", async () => {
    const refusal = new Error("Network Error");
    mocks.deleteMutateAsync.mockRejectedValueOnce(refusal);
    const toastSuccess = vi
      .spyOn(toast, "success")
      .mockImplementation(() => "");
    const { result } = renderActions();

    await expect(
      result.current.confirmBulkDelete(["item-1"], "LOST", "note"),
    ).rejects.toBe(refusal);
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
