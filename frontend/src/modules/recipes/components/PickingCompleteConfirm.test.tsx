import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PickingView from "./PickingView";
import { usePickingSession } from "../hooks/usePickingSession";
import type { PickingItem } from "@/modules/recipes/types/core";

vi.mock("../hooks/usePickingSession", () => ({
  usePickingSession: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const makeItem = (
  ingredientId: string,
  status: PickingItem["status"],
): PickingItem => ({
  ingredient_id: ingredientId,
  name: "Test Ingredient",
  quantity_to_pick: 1,
  uom_symbol: null,
  recommended_item_id: "item-1",
  location: null,
  fefo_days_left: null,
  fefo_expiry_date: null,
  status,
  is_linked: true,
});

const mockSession = {
  state: {
    phase: "active",
    session: {
      picking_session_id: "s1",
      recipe_name: "Test Recipe",
      servings: 1,
      items_to_pick: [],
    },
    items: [] as PickingItem[],
  },
  isLoading: false,
  error: null,
  startSession: vi.fn(),
  scan: vi.fn(),
  resolveDisambiguation: vi.fn(),
  undoPick: vi.fn(),
  dismissFefoMismatch: vi.fn(),
  dismissOpenedSuggestion: vi.fn(),
  completeSession: vi.fn().mockResolvedValue(undefined),
  cancelSession: vi.fn(),
  reset: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  mockSession.completeSession.mockResolvedValue(undefined);
  mockSession.state.items = [];
  vi.mocked(usePickingSession).mockReturnValue(mockSession as never);
});

describe("PickingView — complete session confirmation", () => {
  it("complete button is enabled with 0 picked and asks for explicit confirm", async () => {
    const user = userEvent.setup();
    mockSession.state.items = [
      makeItem("i1", "pending"),
      makeItem("i2", "pending"),
    ];
    render(<PickingView recipeId="r1" recipeName="Test" onClose={vi.fn()} />);

    const completeButton = screen.getByRole("button", {
      name: /finish picking/i,
    });
    expect(completeButton).toBeEnabled();

    await user.click(completeButton);
    // Zero-picked dialog must appear, and completing must NOT happen yet
    expect(screen.getByText(/nothing picked yet/i)).toBeInTheDocument();
    expect(mockSession.completeSession).not.toHaveBeenCalled();
  });

  it("confirming the zero-picked dialog completes the session", async () => {
    const user = userEvent.setup();
    mockSession.state.items = [makeItem("i1", "pending")];
    const onClose = vi.fn();
    render(<PickingView recipeId="r1" recipeName="Test" onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: /finish picking/i }));
    // Two buttons now: footer + dialog confirm — click the dialog one
    const buttons = screen.getAllByRole("button", {
      name: /finish picking/i,
    });
    await user.click(buttons[buttons.length - 1]);
    expect(mockSession.completeSession).toHaveBeenCalledOnce();
  });

  it("uses the standard confirm title when some items are picked", async () => {
    const user = userEvent.setup();
    mockSession.state.items = [
      makeItem("i1", "picked"),
      makeItem("i2", "pending"),
    ];
    render(<PickingView recipeId="r1" recipeName="Test" onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /finish picking/i }));
    expect(screen.getByText(/finish picking\?/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing picked yet/i)).not.toBeInTheDocument();
  });

  it("stops warning about a remainder once there is none", async () => {
    const user = userEvent.setup();
    mockSession.state.items = [makeItem("i1", "picked")];
    render(<PickingView recipeId="r1" recipeName="Test" onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /finish picking/i }));

    expect(
      screen.getByText("Everything on the list is picked. Finish picking?"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/marked as skipped/i)).not.toBeInTheDocument();
  });

  it("shows picked count in the header (1/3 picked)", () => {
    mockSession.state.items = [
      makeItem("i1", "picked"),
      makeItem("i2", "pending"),
      makeItem("i3", "pending"),
    ];
    render(<PickingView recipeId="r1" recipeName="Test" onClose={vi.fn()} />);
    expect(screen.getByText(/1\/3/i)).toBeInTheDocument();
  });
});
