import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ReplenishSuggestionsModal from "./ReplenishSuggestionsModal";
import { useShoppingSuggestionsPreview } from "@/modules/shopping_lists/hooks/useShoppingLists";

// ── mocks ──────────────────────────────────────────────────────────────────────

vi.mock("@/modules/shopping_lists/hooks/useShoppingLists", () => ({
  // The preview asks for suggestions without a list; the modal creates one
  // only once somebody has chosen to buy something.
  useShoppingSuggestionsPreview: vi.fn(() => ({
    data: { suggestions: [] },
    isLoading: false,
  })),
  useAddShoppingItemsToAList: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/ui/Button", () => ({
  default: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props} />
  ),
}));

// ── ReplenishSuggestionsModal ─────────────────────────────────────────────────

describe("ReplenishSuggestionsModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
  });

  it("returns null when isOpen is false", () => {
    const { container } = render(
      <ReplenishSuggestionsModal isOpen={false} onClose={onClose} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders modal title when isOpen is true", () => {
    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);
    expect(screen.getByText("Review Suggestions")).toBeInTheDocument();
  });

  it('renders "no suggestions" state when suggestions list is empty', () => {
    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);
    expect(
      screen.getByText("No new replenishment suggestions."),
    ).toBeInTheDocument();
  });

  it("asks for a choice instead of making it — nothing is selected upfront", () => {
    vi.mocked(useShoppingSuggestionsPreview).mockReturnValue({
      data: {
        suggestions: [
          {
            item_id: "i1",
            name: "Flour 2 kg",
            quantity: 2,
            priority: 0,
            source: "low_stock",
          },
          {
            item_id: "i2",
            name: "Sugar 1 kg",
            quantity: 1,
            priority: 1,
            source: "low_stock",
          },
        ],
      },
      isLoading: false,
    } as never);

    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);

    expect(screen.getByText("Flour 2 kg")).toBeInTheDocument();
    // The subtitle asks the reader to choose; the screen must not have
    // chosen already. Nothing selected means the confirm stays disabled —
    // a hasty click adds nothing.
    expect(
      screen.getByRole("button", { name: /Add selected \(0\)/ }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /Add selected \(2\)/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps two same-named proposals apart — one tick, one row", () => {
    // The engine's low-stock source names a template, not an item, and one
    // organization may hold two templates with one name. Keyed by the name,
    // the two rows collided: ticking one ticked both, and the confirm put
    // two identical rows on the list.
    vi.mocked(useShoppingSuggestionsPreview).mockReturnValue({
      data: {
        suggestions: [
          {
            item_id: null,
            template_id: "t-plain",
            name: "Frozen peas",
            quantity: "1",
            source: "auto_low_stock",
            priority: 1,
          },
          {
            item_id: null,
            template_id: "t-hortex",
            name: "Frozen peas",
            quantity: "1",
            source: "auto_low_stock",
            priority: 1,
          },
          {
            item_id: null,
            template_id: "t-oat",
            name: "Oat milk",
            quantity: "1",
            source: "auto_low_stock",
            priority: 1,
          },
        ],
      },
      isLoading: false,
    } as never);

    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);

    const boxes = screen.getAllByRole("checkbox", { name: /Frozen peas/ });
    expect(boxes).toHaveLength(2);

    fireEvent.click(boxes[0]);
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: /Add selected \(1\)/ }),
    ).toBeEnabled();
  });

  it("starts from nothing again after a cancel — a tick does not outlive the visit", () => {
    vi.mocked(useShoppingSuggestionsPreview).mockReturnValue({
      data: {
        suggestions: [
          {
            item_id: "i1",
            name: "Flour 2 kg",
            quantity: 2,
            priority: 0,
            source: "low_stock",
          },
        ],
      },
      isLoading: false,
    } as never);

    const { rerender } = render(
      <ReplenishSuggestionsModal isOpen={true} onClose={onClose} />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /Flour 2 kg/ }));
    expect(
      screen.getByRole("button", { name: /Add selected \(1\)/ }),
    ).toBeEnabled();

    // Cancel closes the sheet, it does not unmount the component — so the
    // opening edge is what has to clear the tick. It used to survive and
    // come back on the next visit.
    rerender(<ReplenishSuggestionsModal isOpen={false} onClose={onClose} />);
    rerender(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);

    expect(
      screen.getByRole("button", { name: /Add selected \(0\)/ }),
    ).toBeDisabled();
  });

  it("reaches a row by keyboard and ticks it with Space", async () => {
    vi.mocked(useShoppingSuggestionsPreview).mockReturnValue({
      data: {
        suggestions: [
          {
            item_id: "i1",
            name: "Flour 2 kg",
            quantity: 2,
            priority: 0,
            source: "low_stock",
          },
        ],
      },
      isLoading: false,
    } as never);

    const user = userEvent.setup();
    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);

    const checkbox = screen.getByRole("checkbox", { name: /Flour 2 kg/ });
    // A div with onClick is not in the tab order; a real checkbox is.
    expect(checkbox.tabIndex).toBe(0);
    checkbox.focus();
    await user.keyboard(" ");
    expect(
      screen.getByRole("button", { name: /Add selected \(1\)/ }),
    ).toBeEnabled();
  });

  it("calls onClose when close button is clicked", () => {
    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ReplenishSuggestionsModal — the wire's quantity is a string", () => {
  const onClose = vi.fn();
  const mockUseShoppingSuggestions = vi.mocked(useShoppingSuggestionsPreview);

  beforeEach(() => {
    onClose.mockClear();
    mockUseShoppingSuggestions.mockImplementation(
      () => ({ data: { suggestions: [] }, isLoading: false }) as never,
    );
  });

  it("asks for shortages, not for everything the engine knows", () => {
    // The button that opens this hangs on the tile counting shortages,
    // and the engine returns every source it knows unless asked
    // otherwise — which is how a low-stock button came to open a
    // screenful of products that had *expired*.
    mockUseShoppingSuggestions.mockReturnValue({
      data: { suggestions: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof useShoppingSuggestionsPreview>);

    render(<ReplenishSuggestionsModal isOpen onClose={vi.fn()} />);

    expect(mockUseShoppingSuggestions).toHaveBeenCalledWith(
      true,
      expect.objectContaining({
        include_low_stock: true,
        include_expiring: false,
        include_frequent: false,
      }),
    );
  });

  it("steps a wire-string quantity numerically, not by concatenation", () => {
    // The API serializes a Decimal as a string ("1"), so the old code held
    // the string in its stepper state and the first plus produced "11".
    mockUseShoppingSuggestions.mockReturnValue({
      data: {
        suggestions: [
          {
            item_id: null,
            category_id: null,
            name: "Mąka",
            quantity: "1",
            uom_symbol: "kg",
            source: "manual",
            priority: 0,
            estimated_price: null,
          },
        ],
      },
      isLoading: false,
    } as never);

    render(<ReplenishSuggestionsModal isOpen={true} onClose={onClose} />);

    fireEvent.click(screen.getByLabelText("Increase"));
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.queryByText("11")).not.toBeInTheDocument();
  });
});
