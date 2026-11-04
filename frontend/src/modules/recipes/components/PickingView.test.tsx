import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PickingView from "./PickingView";
import { toast } from "sonner";
import { QueryWrapper } from "@/test/queryWrapper";
import type {
  PickingItem,
  RecipeIngredient,
} from "@/modules/recipes/types/core";

// PickingView uses usePickingSession which calls API — mock it.
// Mutable via vi.hoisted so individual tests can switch phases.
const mockHook = vi.hoisted(() => ({
  state: { phase: "idle" } as unknown,
  isLoading: false,
  error: null as string | null,
  refusals: {} as Record<string, string>,
  startSession: vi.fn(),
  scan: vi.fn(),
  resolveDisambiguation: vi.fn(),
  undoPick: vi.fn(),
  dismissFefoMismatch: vi.fn(),
  dismissOpenedSuggestion: vi.fn(),
  completeSession: vi.fn(),
  cancelSession: vi.fn(),
  reset: vi.fn(),
}));

vi.mock("../hooks/usePickingSession", () => ({
  usePickingSession: () => mockHook,
}));

// The close path reaches for the API directly, not through the hook — spy
// on the one method it calls while leaving the rest of the module real.
const cancelPicking = vi.hoisted(() => vi.fn());
vi.mock("@/modules/recipes/api/recipes", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/recipes/api/recipes")>();
  return {
    ...actual,
    recipesApi: { ...actual.recipesApi, cancelPicking },
  };
});

vi.mock("sonner", () => ({
  // `toast(...)` itself is a call too — the cancel path says its sentence
  // through it, so a plain methods-only object throws "not a function".
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

beforeEach(() => {
  mockHook.state = { phase: "idle" };
  mockHook.completeSession.mockClear();
  mockHook.reset.mockClear();
});

const makeIngredient = (
  quantity: number,
  uom_symbol: string,
): RecipeIngredient => ({
  id: crypto.randomUUID(),
  recipe_id: "r1",
  name: "Test",
  template_id: null,
  ingredient_group_name: null,
  quantity: String(quantity),
  uom_id: null,
  uom_symbol,
  is_optional: false,
  is_spice: false,
  sort_order: 0,
  calories_kcal_per_100g: null,
  picking_skip: null,
  display_text: null,
  original_quantity: null,
  original_unit_text: null,
  price: null,
  price_uom_id: null,
  price_currency: null,
  allergens: [],
});

const defaultProps = {
  recipeId: "r1",
  recipeName: "Test Recipe",
  onClose: vi.fn(),
};

describe("PickingView — idle phase rendering", () => {
  it("renders servings selector", () => {
    render(
      <QueryWrapper>
        <PickingView {...defaultProps} defaultServings={4} />
      </QueryWrapper>,
    );
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("renders start and cancel buttons", () => {
    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );
    // i18n keys (the button names the stock movement)
    expect(
      screen.getByRole("button", { name: /take from stock|pobierz ze stanu/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/cancel|Anuluj/i)).toBeInTheDocument();
  });

  it("calls onClose when cancel is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <QueryWrapper>
        <PickingView {...defaultProps} onClose={onClose} />
      </QueryWrapper>,
    );
    await user.click(screen.getByText(/cancel|Anuluj/i));
    expect(onClose).toHaveBeenCalledOnce();
    // Closing the opening dialog is not completing anything: the click
    // event must not travel on as the "completed" argument, or the recipe
    // page shows Completed for a session that never started.
    expect(onClose).toHaveBeenCalledWith();
  });

  it("starts a recipe with no links at all, since names still pick", () => {
    render(
      <PickingView
        {...defaultProps}
        ingredients={[makeIngredient(100, "g"), makeIngredient(2, "pcs")]}
      />,
    );
    expect(
      screen.getByRole("button", { name: /take from stock|pobierz ze stanu/i }),
    ).toBeInTheDocument();
  });
});

describe("PickingView — complete flow", () => {
  it("passes the completed session id to onClose", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mockHook.state = {
      phase: "active",
      session: {
        picking_session_id: "sess-1",
        recipe_name: "Test Recipe",
        servings: 2,
        items_to_pick: [],
      },
      items: [],
    };
    mockHook.completeSession.mockResolvedValue(true);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} onClose={onClose} />
      </QueryWrapper>,
    );

    // Footer "Complete" button opens the confirm dialog…
    await user.click(
      screen.getAllByRole("button", {
        name: /zakończ pobieranie|finish picking/i,
      })[0],
    );
    // …and the dialog's confirm button triggers completion.
    const dialog = screen.getByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", {
        name: /zakończ pobieranie|finish picking/i,
      }),
    );

    expect(mockHook.completeSession).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledWith(true, "sess-1");
  });
});

describe("PickingView — the resumed session stays on the sheet", () => {
  it("badges it and keeps the session's own servings, not the asked-for ones", () => {
    mockHook.state = {
      phase: "active",
      session: {
        picking_session_id: "sess-1",
        recipe_name: "Test Recipe",
        servings: 8,
        resumed: true,
        items_to_pick: [],
      },
      items: [],
    };

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} defaultServings={4} />
      </QueryWrapper>,
    );

    // The dialog used to say "Servings to cook: 4" in the form and then open
    // an eight-serving checklist with only a few-seconds toast in between.
    expect(screen.getByText("Resumed")).toBeInTheDocument();
    expect(screen.getByText(/8 servings/)).toBeInTheDocument();
  });

  it("counts one serving in the singular in the resumed toast", async () => {
    const user = userEvent.setup();
    mockHook.startSession.mockResolvedValue({
      picking_session_id: "sess-1",
      recipe_name: "Test Recipe",
      servings: 1,
      resumed: true,
      items_to_pick: [],
    });

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );
    await user.click(
      screen.getByRole("button", { name: /take from stock|pobierz ze stanu/i }),
    );

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        "Picked up where you left off — unfinished picking for 1 serving.",
      );
    });
  });
});

const makePickingItem = (
  overrides: Partial<PickingItem> & { ingredient_id: string; name: string },
): PickingItem => ({
  quantity_to_pick: 2,
  uom_symbol: "kg",
  recommended_item_id: "item-1",
  location: null,
  fefo_days_left: null,
  fefo_expiry_date: null,
  status: "pending",
  is_linked: true,
  ...overrides,
});

const activeStateWith = (items: PickingItem[]) => ({
  phase: "active",
  session: {
    picking_session_id: "sess-1",
    recipe_name: "Test Recipe",
    servings: 2,
    items_to_pick: [],
  },
  items,
});

describe("PickingView — tapping an ingredient", () => {
  it("says the recommended record is a suggestion, not the cook's choice", async () => {
    mockHook.scan.mockResolvedValue(null);
    mockHook.state = activeStateWith([
      makePickingItem({ ingredient_id: "i1", name: "Flour" }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );
    await userEvent.click(screen.getByText("Flour"));

    expect(mockHook.scan).toHaveBeenCalledWith({
      item_id: "item-1",
      from_checklist: true,
    });
  });
});

describe("PickingView — the unlinked notice", () => {
  beforeEach(() => {
    mockHook.cancelSession.mockClear();
    mockHook.reset.mockClear();
  });

  it("counts only the rows nothing could reach, and says so once", () => {
    mockHook.state = activeStateWith([
      makePickingItem({ ingredient_id: "i1", name: "Flour" }),
      // Linked but sold out — a stock fact, not a wiring one.
      makePickingItem({
        ingredient_id: "i2",
        name: "Black pepper",
        recommended_item_id: null,
        status: "missing",
      }),
      // Unlinked and matched by name — pickable, so not in the count.
      makePickingItem({
        ingredient_id: "i3",
        name: "Chickpeas",
        is_linked: false,
      }),
      makePickingItem({
        ingredient_id: "i4",
        name: "Homemade sauce",
        recommended_item_id: null,
        status: "unknown",
        is_linked: false,
      }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );

    expect(
      screen.getByText(/1 of 4 ingredients is not linked to a product/),
    ).toBeInTheDocument();
  });

  it("stays away when every row can reach stock", () => {
    mockHook.state = activeStateWith([
      makePickingItem({ ingredient_id: "i1", name: "Flour" }),
      makePickingItem({
        ingredient_id: "i2",
        name: "Black pepper",
        recommended_item_id: null,
        status: "missing",
      }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );

    expect(screen.queryByText(/not linked to a product/i)).toBeNull();
  });

  it("wears a theme-aware colour on the amber callout", () => {
    mockHook.state = activeStateWith([
      makePickingItem({
        ingredient_id: "i1",
        name: "Homemade sauce",
        recommended_item_id: null,
        status: "unknown",
        is_linked: false,
      }),
      makePickingItem({ ingredient_id: "i2", name: "Flour" }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );

    const text = screen.getByText(/not linked to a product/i);
    // The amber tint flips dark under `.dark`; only a theme-aware token stays
    // readable on it — a ramp step like text-amber-800 would go dark-on-dark.
    expect(text.className).toContain("text-on-warning");
    expect(text.closest("div[class*='bg-amber-50']")).not.toBeNull();
  });

  it("says what is actually wrong when nothing at all is on the shelf", () => {
    mockHook.state = activeStateWith([
      makePickingItem({
        ingredient_id: "i1",
        name: "Flour",
        recommended_item_id: null,
        status: "missing",
      }),
      makePickingItem({
        ingredient_id: "i2",
        name: "Homemade sauce",
        recommended_item_id: null,
        status: "unknown",
        is_linked: false,
      }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} />
      </QueryWrapper>,
    );

    expect(
      screen.getByText("Nothing from this recipe is in stock right now"),
    ).toBeInTheDocument();
  });

  it("keeps the session and re-reads it after a link lands", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mockHook.state = activeStateWith([
      makePickingItem({
        ingredient_id: "i1",
        name: "Homemade sauce",
        recommended_item_id: null,
        status: "unknown",
        is_linked: false,
      }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} onClose={onClose} />
      </QueryWrapper>,
    );

    // The row nothing matched carries the linker itself.
    await user.click(screen.getByTitle("Link to product"));

    expect(mockHook.cancelSession).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("PickingView — closing keeps the session resumable", () => {
  beforeEach(() => {
    cancelPicking.mockClear();
    mockHook.reset.mockClear();
  });

  it("does not cancel the session when the sheet is closed mid-pick", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    // Something already left the shelf — closing now must not put it back
    // without a decision, exactly as leaving via the browser's back arrow
    // never did.
    mockHook.state = activeStateWith([
      makePickingItem({
        ingredient_id: "i1",
        name: "Rice",
        status: "picked",
      }),
    ]);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} onClose={onClose} />
      </QueryWrapper>,
    );

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(cancelPicking).not.toHaveBeenCalled();
    expect(mockHook.reset).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("still cancels through the explicit Cancel action", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mockHook.state = activeStateWith([
      makePickingItem({
        ingredient_id: "i1",
        name: "Rice",
        status: "picked",
      }),
    ]);
    mockHook.cancelSession.mockResolvedValue(true);

    render(
      <QueryWrapper>
        <PickingView {...defaultProps} onClose={onClose} />
      </QueryWrapper>,
    );

    // The named decision — "Cancel picking" — is the one path allowed to
    // put things back, and it says so with its toast.
    await user.click(
      screen.getByRole("button", { name: /cancel picking|anuluj pobieranie/i }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(mockHook.cancelSession).toHaveBeenCalledOnce();
    expect(cancelPicking).not.toHaveBeenCalled();
  });
});

describe("PickingView — clean servings hint", () => {
  it("does NOT show hint when no countable ingredients", () => {
    const ingredients = [makeIngredient(200, "g"), makeIngredient(0.5, "l")];
    render(
      <PickingView
        {...defaultProps}
        defaultServings={3}
        baseServings={4}
        ingredients={ingredients}
      />,
    );
    expect(
      screen.queryByText(/porcji dla pełnych|for whole quantities/i),
    ).not.toBeInTheDocument();
  });

  it("does NOT show hint when current servings already give whole numbers", () => {
    // 2 jajka / 4 porcje base → 4 porcje current: 2 jajka (whole)
    const ingredients = [makeIngredient(2, "jajka")];
    render(
      <PickingView
        {...defaultProps}
        defaultServings={4}
        baseServings={4}
        ingredients={ingredients}
      />,
    );
    expect(
      screen.queryByText(/porcji dla pełnych|for whole quantities/i),
    ).not.toBeInTheDocument();
  });

  it("shows hint when current servings produce fractional countables", () => {
    // 2 jajka / 4 porcje base → 3 porcje: 1.5 jajka (fractional)
    const ingredients = [makeIngredient(2, "jajka")];
    render(
      <PickingView
        {...defaultProps}
        defaultServings={3}
        baseServings={4}
        ingredients={ingredients}
      />,
    );
    // Should show hint mentioning nearby clean counts (2 or 4)
    expect(
      screen.getByText(/porcji dla pełnych|for whole quantities/i),
    ).toBeInTheDocument();
  });

  it("hint mentions a valid clean serving count", () => {
    // 1 szt / 2 porcje base → 3 current: 1.5 (fractional). Clean: 2, 4, 6...
    const ingredients = [makeIngredient(1, "szt")];
    render(
      <PickingView
        {...defaultProps}
        defaultServings={3}
        baseServings={2}
        ingredients={ingredients}
      />,
    );
    const hint = screen.getByText(/porcji dla pełnych|for whole quantities/i);
    // Should contain "2" or "4" (nearby even numbers)
    expect(hint.textContent).toMatch(/[24]/);
  });

  it("does NOT show hint when ingredients prop is not passed", () => {
    render(
      <PickingView
        {...defaultProps}
        defaultServings={3}
        baseServings={4}
        // no ingredients prop
      />,
    );
    expect(
      screen.queryByText(/porcji dla pełnych|for whole quantities/i),
    ).not.toBeInTheDocument();
  });
});

describe("PickingView — servings selector interaction", () => {
  it("updates hint when servings change to clean number", async () => {
    const user = userEvent.setup();
    // 2 jajka / 4 base → start at 3 (fractional) → click + → 4 (whole, hint vanishes)
    const ingredients = [makeIngredient(2, "jajka")];
    render(
      <PickingView
        {...defaultProps}
        defaultServings={3}
        baseServings={4}
        ingredients={ingredients}
      />,
    );
    expect(
      screen.getByText(/porcji dla pełnych|for whole quantities/i),
    ).toBeInTheDocument();
    await user.click(screen.getByText("+"));
    // Now at 4 servings → no hint
    expect(
      screen.queryByText(/porcji dla pełnych|for whole quantities/i),
    ).not.toBeInTheDocument();
  });

  it("shows hint when servings change to fractional count", async () => {
    const user = userEvent.setup();
    // 2 jajka / 4 base → start at 4 (whole) → click − → 3 (fractional)
    const ingredients = [makeIngredient(2, "jajka")];
    render(
      <PickingView
        {...defaultProps}
        defaultServings={4}
        baseServings={4}
        ingredients={ingredients}
      />,
    );
    expect(
      screen.queryByText(/porcji dla pełnych|for whole quantities/i),
    ).not.toBeInTheDocument();
    await user.click(screen.getByText("−"));
    expect(
      screen.getByText(/porcji dla pełnych|for whole quantities/i),
    ).toBeInTheDocument();
  });
});
