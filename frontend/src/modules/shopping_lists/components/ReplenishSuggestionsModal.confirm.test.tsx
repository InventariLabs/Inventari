import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import { QueryWrapper } from "@/test/queryWrapper";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
import { useShoppingSuggestionsPreview } from "@/modules/shopping_lists/hooks/useShoppingLists";
import ReplenishSuggestionsModal from "./ReplenishSuggestionsModal";

type MutateOptions = {
  onSuccess?: (data: unknown) => void;
  onError?: (error: unknown) => void;
};

const mocks = vi.hoisted(() => ({ addItems: vi.fn() }));

vi.mock("@/modules/shopping_lists/hooks/useShoppingLists", () => ({
  useShoppingSuggestionsPreview: vi.fn(),
  useAddShoppingItemsToAList: () => ({
    mutate: mocks.addItems,
    isPending: false,
  }),
}));

vi.mock("@/modules/shopping_lists/api/shopping-lists", () => ({
  shoppingListsApi: { ensureActiveList: vi.fn() },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const suggestions = [
  {
    source: "low_stock",
    name: "Flour",
    template_id: "tpl-flour",
    item_id: null,
    category_id: "cat-1",
    quantity: "2",
    priority: 0,
    estimated_price: null,
    notes: "below minimum",
    uom_symbol: null,
  },
  {
    source: "low_stock",
    name: "Sugar",
    template_id: "tpl-sugar",
    item_id: null,
    category_id: null,
    quantity: "1",
    priority: 1,
    estimated_price: "4.20",
    notes: null,
    uom_symbol: null,
  },
];

function lastOptions(): MutateOptions {
  return mocks.addItems.mock.calls.at(-1)?.[1] as MutateOptions;
}

function open() {
  const onClose = vi.fn();
  render(<ReplenishSuggestionsModal isOpen onClose={onClose} />, {
    wrapper: QueryWrapper,
  });
  return { onClose };
}

/**
 * What the confirm puts on the shopping list: only the ticked rows, with the
 * quantity and urgency the reader set on this screen. A confirm that sends
 * the engine's defaults over the reader's steppers, adds unticked rows, or
 * swallows a vanished list as a generic error buys the wrong things.
 */
describe("ReplenishSuggestionsModal — the confirm sends what the reader chose", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useShoppingSuggestionsPreview).mockReturnValue({
      data: { suggestions },
      isLoading: false,
    } as unknown as ReturnType<typeof useShoppingSuggestionsPreview>);
    vi.mocked(shoppingListsApi.ensureActiveList).mockResolvedValue("list-1");
  });

  it("adds the ticked row with its stepped quantity and urgency, to the active list", async () => {
    const user = userEvent.setup();
    const { onClose } = open();

    const [flourTick] = screen.getAllByRole("checkbox");
    await user.click(flourTick!);
    const increase = screen.getAllByRole("button", { name: "Increase" })[0]!;
    await user.click(increase);
    await user.click(increase);
    await user.click(screen.getAllByRole("button", { name: "Decrease" })[0]!);
    await user.click(screen.getAllByRole("button", { name: "Urgent" })[0]!);

    await user.click(screen.getByRole("button", { name: "Add selected (1)" }));

    await waitFor(() => expect(mocks.addItems).toHaveBeenCalled());
    expect(mocks.addItems.mock.calls[0]?.[0]).toEqual({
      listId: "list-1",
      items: [
        {
          item_id: undefined,
          template_id: "tpl-flour",
          category_id: "cat-1",
          name: "Flour",
          quantity: 3,
          priority: 2,
          estimated_price: undefined,
          notes: "below minimum",
        },
      ],
    });

    lastOptions().onSuccess?.([{}]);
    expect(toast.success).toHaveBeenCalledWith(
      "Added missing products to shopping list",
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("takes a row off again when its tick is cleared, and urgency back off", async () => {
    const user = userEvent.setup();
    open();

    const [flourTick, sugarTick] = screen.getAllByRole("checkbox");
    await user.click(flourTick!);
    await user.click(sugarTick!);
    await user.click(flourTick!);
    const urgent = screen.getAllByRole("button", { name: "Urgent" })[1]!;
    await user.click(urgent);
    await user.click(urgent);

    await user.click(screen.getByRole("button", { name: "Add selected (1)" }));

    await waitFor(() => expect(mocks.addItems).toHaveBeenCalled());
    const sent = mocks.addItems.mock.calls[0]?.[0] as {
      items: { name: string; priority: number; estimated_price?: string }[];
    };
    expect(sent.items).toHaveLength(1);
    expect(sent.items[0]).toMatchObject({
      name: "Sugar",
      priority: 0,
      estimated_price: "4.20",
    });
  });

  it("does not step a quantity below one", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getAllByRole("checkbox")[1]!);
    await user.click(screen.getAllByRole("button", { name: "Decrease" })[1]!);
    await user.click(screen.getByRole("button", { name: "Add selected (1)" }));

    await waitFor(() => expect(mocks.addItems).toHaveBeenCalled());
    const sent = mocks.addItems.mock.calls[0]?.[0] as {
      items: { quantity: number }[];
    };
    expect(sent.items[0]?.quantity).toBe(1);
  });

  it("names a list that vanished, apart from any other failure", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getAllByRole("checkbox")[0]!);
    await user.click(screen.getByRole("button", { name: "Add selected (1)" }));
    await waitFor(() => expect(mocks.addItems).toHaveBeenCalled());

    lastOptions().onError?.({ response: { status: 404 } });
    lastOptions().onError?.(new Error("boom"));

    const messages = vi.mocked(toast.error).mock.calls.map((c) => c[0]);
    expect(messages).toHaveLength(2);
    expect(messages[0]).not.toBe(messages[1]);
  });

  it("adds nothing and reports it when no list could be made", async () => {
    vi.mocked(shoppingListsApi.ensureActiveList).mockRejectedValue(
      new Error("no list"),
    );
    const user = userEvent.setup();
    const { onClose } = open();

    await user.click(screen.getAllByRole("checkbox")[0]!);
    await user.click(screen.getByRole("button", { name: "Add selected (1)" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(mocks.addItems).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("just closes when the engine had nothing to propose", async () => {
    vi.mocked(useShoppingSuggestionsPreview).mockReturnValue({
      data: { suggestions: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof useShoppingSuggestionsPreview>);
    const user = userEvent.setup();
    const { onClose } = open();

    await user.click(screen.getByRole("button", { name: "Add selected (0)" }));

    expect(onClose).toHaveBeenCalled();
    expect(shoppingListsApi.ensureActiveList).not.toHaveBeenCalled();
  });
});
