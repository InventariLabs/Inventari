import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { CompositionTab } from "./CompositionTab";
import { withLanguage } from "@/test/mocks/i18n";
import type { BomLine, MakerRecipe } from "@/modules/maker/types/maker";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents_products";

const updateRecipeMutate = vi.fn();
const updateBomLineMutate = vi.fn();
const addBomLineMutate = vi.fn();
const deleteBomLineMutate = vi.fn();

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useUpdateMakerRecipe: () => ({
    mutateAsync: updateRecipeMutate,
    isPending: false,
  }),
  useUpdateBomLine: () => ({
    mutateAsync: updateBomLineMutate,
    isPending: false,
  }),
  useAddBomLineToRecipe: () => ({
    mutate: addBomLineMutate,
    isPending: false,
  }),
  useDeleteBomLine: () => ({
    mutateAsync: deleteBomLineMutate,
    isPending: false,
  }),
}));

const unitsRead = vi.hoisted(() => ({ failed: false }));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastError },
}));

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: unitsRead.failed
      ? undefined
      : [
          {
            id: "uom-kg",
            symbol: "kg",
            name: "Kilogram",
            category_id: "cat-weight",
            factor: 1000,
          },
        ],
    isError: unitsRead.failed,
    refetch: vi.fn(),
  }),
  // UomSelect reads the categorised list; the flat one is for lookups.
  useUoms: () => ({
    data: [
      {
        id: "cat-weight",
        name: "Weight",
        uoms: [
          {
            id: "uom-kg",
            symbol: "kg",
            name: "Kilogram",
            category_id: "cat-weight",
            factor: 1000,
          },
        ],
      },
    ],
    isLoading: false,
  }),
}));

vi.mock("@/modules/maker/components/ProductSearchInput", () => ({
  ProductSearchInput: ({
    onSelect,
  }: {
    onSelect: (product: ProductSearchResult) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onSelect({
          product_template_id: "tpl-oats",
          name: "Oats",
          sku: null,
          barcode: null,
          brand: null,
          // The catalogue's own unit for this product. A product with none
          // leaves the picker empty on purpose (the maker cannot tell whether
          // the line's unit would be convertible), and these tests are about
          // adding a line, not about that case.
          uom_id: "uom-kg",
          uom_symbol: "kg",
          image_url: null,
          is_stub: false,
        })
      }
    >
      pick-ingredient
    </button>
  ),
}));

const line: BomLine = {
  id: "line-1",
  organization_id: "org-1",
  parent_template_id: "tpl-1",
  child_template_id: "tpl-oats",
  child_template_name: "Oats",
  qty_per_batch: "2.0000",
  uom_id: "uom-kg",
  unit: "kg",
  yield_loss_pct: "0.00",
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const recipe: MakerRecipe = {
  id: "r-1",
  organization_id: "org-1",
  output_template_id: "tpl-1",
  name: "Granola Bars",
  batch_yield_qty: "5",
  batch_yield_uom_id: null,
  process_steps: ["Heat oven", "Mix dry ingredients"],
  reference_price: null,
  is_default: true,
  source_recipe_id: null,
  source_snapshot_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  output_template_name: "Granola Bars 500g",
  cost_lines: [],
  lines: [],
  estimated_unit_cost: null,
};

function renderTab(overrides: Partial<MakerRecipe> = {}) {
  render(<CompositionTab recipe={{ ...recipe, ...overrides }} />);
}

describe("CompositionTab yield editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The tab edits the formula, so the tests render the manager's account.
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  it("edits the batch yield quantity via PATCH", async () => {
    renderTab();
    expect(screen.getByText("This BOM makes 5")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("maker-yield-edit"));
    const input = screen.getByTestId("maker-yield-input");
    fireEvent.change(input, { target: { value: "8" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("maker-yield-save"));
    });

    expect(updateRecipeMutate).toHaveBeenCalledWith({
      recipeId: "r-1",
      data: { batch_yield_qty: "8" },
    });
  });

  it("names the yield's unit when the BOM takes it from its product", () => {
    // A BOM made in its product's unit stores no unit of its own; the server
    // sends the product's symbol, and the header beside this tab already
    // reads "This BOM makes 5 kg".
    renderTab({ batch_yield_uom_id: null, batch_yield_uom_symbol: "kg" });

    expect(screen.getByText("This BOM makes 5 kg")).toBeInTheDocument();
  });

  it("shows the yield without the column's zero padding, and edits it that way", () => {
    renderTab({ batch_yield_qty: "12.0000" });
    expect(screen.getByText("This BOM makes 12")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("maker-yield-edit"));
    expect(screen.getByTestId("maker-yield-input")).toHaveValue(12);
  });

  it("refuses a zero yield out loud instead of silently restoring the old one", () => {
    renderTab();
    fireEvent.click(screen.getByTestId("maker-yield-edit"));
    fireEvent.change(screen.getByTestId("maker-yield-input"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByTestId("maker-yield-save"));

    expect(updateRecipeMutate).not.toHaveBeenCalled();
    // The field stays open — the user's value is still there to correct.
    expect(screen.getByTestId("maker-yield-input")).toBeInTheDocument();
  });

  it("explains what the number means once the field is open", () => {
    renderTab();
    fireEvent.click(screen.getByTestId("maker-yield-edit"));
    expect(
      screen.getByText(/How much one batch of this BOM makes/),
    ).toBeInTheDocument();
  });
});

describe("CompositionTab ingredients", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  it("offers the add form on an empty recipe instead of a dead end", () => {
    renderTab();
    expect(
      screen.getByText("No ingredients yet — add the first one below."),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("maker-composition-add-line"),
    ).toBeInTheDocument();
  });

  it("adds an ingredient to this recipe, not to the product's default one", () => {
    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "pick-ingredient" }));
    fireEvent.change(screen.getByTestId("maker-composition-qty-input"), {
      target: { value: "1.5" },
    });
    fireEvent.click(screen.getByTestId("maker-composition-add-line"));

    expect(addBomLineMutate).toHaveBeenCalledWith(
      {
        recipeId: "r-1",
        data: {
          child_template_id: "tpl-oats",
          qty_per_batch: "1.5",
          unit: "kg",
          uom_id: "uom-kg",
          yield_loss_pct: "0",
          notes: null,
        },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("sends yield loss and notes from the More section", () => {
    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "pick-ingredient" }));
    fireEvent.click(screen.getByTestId("maker-composition-more-toggle"));
    fireEvent.change(screen.getByTestId("maker-composition-yield-input"), {
      target: { value: "12" },
    });
    fireEvent.change(screen.getByTestId("maker-composition-notes-input"), {
      target: { value: "Peel before weighing" },
    });
    fireEvent.click(screen.getByTestId("maker-composition-add-line"));

    expect(addBomLineMutate.mock.calls[0][0].data).toMatchObject({
      yield_loss_pct: "12",
      notes: "Peel before weighing",
    });
  });

  it("keeps the extra fields folded away until asked for", () => {
    renderTab();
    expect(
      screen.queryByTestId("maker-composition-yield-input"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-composition-notes-input"),
    ).not.toBeInTheDocument();
  });

  it("keeps the add button disabled until a product and a positive qty are set", () => {
    renderTab();
    expect(screen.getByTestId("maker-composition-add-line")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "pick-ingredient" }));
    expect(screen.getByTestId("maker-composition-add-line")).toBeEnabled();

    fireEvent.change(screen.getByTestId("maker-composition-qty-input"), {
      target: { value: "0" },
    });
    expect(screen.getByTestId("maker-composition-add-line")).toBeDisabled();
  });

  it("renders line amounts without the scale padding", () => {
    renderTab({ lines: [{ ...line, yield_loss_pct: "7.50" }] });
    expect(screen.getByText("2 kg")).toBeInTheDocument();
    expect(screen.getByText("+7.5%")).toBeInTheDocument();
  });

  it("lets an ingredient row wrap, and keeps the name a readable width", () => {
    // jsdom has no layout, so the wrap is pinned by its classes. At 320px the
    // name shared one row with the amount and two icons and was left 56px:
    // "Da…" and "W…" for two different plums and sugars.
    renderTab({ lines: [line] });
    const name = screen.getByText(line.child_template_name ?? "", {
      selector: "span.truncate",
    });
    const row = name.parentElement as HTMLElement;
    expect(row.className).toContain("flex-wrap");
    expect(name.className).toContain("min-w-[7rem]");
    // The amount, the yield note and the actions travel as one group, so they
    // drop under the name together instead of one by one.
    const amount = screen.getByText("2 kg");
    expect(amount.parentElement?.className).toContain("ml-auto");
  });

  it("writes line amounts with the translated unit and the reader's decimal mark", async () => {
    // "2.5 pcs" was the wire's sentence; the interface's is "2,5 szt.".
    // One formatter owns the number and the unit together.
    await withLanguage("pl", () => {
      renderTab({
        lines: [{ ...line, qty_per_batch: "2.5000", unit: "pcs" }],
      });

      expect(screen.getByText("2,5 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/2\.5\s+pcs/)).not.toBeInTheDocument();
    });
  });

  it("removes an ingredient only after the confirmation is accepted", async () => {
    renderTab({ lines: [line] });
    fireEvent.click(screen.getByTestId("maker-composition-delete-line"));
    expect(deleteBomLineMutate).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    });

    expect(deleteBomLineMutate).toHaveBeenCalledWith({
      recipeId: "r-1",
      lineId: "line-1",
    });
  });

  it("edits the unit with the shared picker, showing the line's own unit once", () => {
    // The native list this replaced opened with the current unit as a blank
    // option and then listed it again with a raw English name from the
    // database — "kg" above "kg — Kilogram" in a Polish interface.
    renderTab({ lines: [line] });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    const pickers = screen.getAllByRole("button", { name: /^Unit\b/ });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(
      screen.getAllByRole("button", { name: "Unit kg" }).length,
    ).toBeGreaterThan(0);
    expect(pickers.every((b) => !b.textContent?.includes("Kilogram"))).toBe(
      true,
    );
  });
});

describe("CompositionTab legacy unit while the units are unavailable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    unitsRead.failed = false;
    signOut();
  });

  const legacy = { ...line, uom_id: null };

  it("reads a legacy line's unit back off its symbol once the catalogue is there", () => {
    renderTab({ lines: [legacy] });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(
      screen.getAllByRole("button", { name: "Unit kg" }).length,
    ).toBeGreaterThan(0);
  });

  it("does not open the editor on a unit that only looks unset when the units failed", () => {
    // With no catalogue the symbol resolves to nothing and the picker would
    // show an em dash for a line that has a unit.
    unitsRead.failed = true;
    renderTab({ lines: [legacy] });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(toastError).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("maker-yield-input")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save" }),
    ).not.toBeInTheDocument();
  });
});

describe("CompositionTab process steps editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  it("adds and removes steps, then saves the list via PATCH", async () => {
    renderTab();
    expect(screen.getByText("Heat oven")).toBeInTheDocument();
    expect(screen.getByText("Mix dry ingredients")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("maker-steps-edit"));

    // Add a new step.
    fireEvent.change(screen.getByTestId("maker-steps-input"), {
      target: { value: "Bake for 20 min" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    expect(screen.getByText("Bake for 20 min")).toBeInTheDocument();

    // Remove the second step.
    const deleteButtons = screen.getAllByLabelText("Delete");
    fireEvent.click(deleteButtons[1]);
    expect(screen.queryByText("Mix dry ingredients")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByTestId("maker-steps-save"));
    });

    expect(updateRecipeMutate).toHaveBeenCalledWith({
      recipeId: "r-1",
      data: { process_steps: ["Heat oven", "Bake for 20 min"] },
    });
  });

  it("keeps a multi-line step intact and adds it with ctrl+enter", async () => {
    renderTab({ process_steps: [] });
    fireEvent.click(screen.getByTestId("maker-steps-edit"));

    const field = screen.getByTestId("maker-steps-input");
    expect(field.tagName).toBe("TEXTAREA");

    const longStep = "Zmielić mięso\nDodać przyprawy i wymieszać";
    fireEvent.change(field, { target: { value: longStep } });
    // A bare Enter belongs to the text now, not to the form: the draft is
    // untouched and the field keeps what was typed.
    fireEvent.keyDown(field, { key: "Enter" });
    expect(field).toHaveValue(longStep);
    expect(screen.queryByLabelText("Delete")).not.toBeInTheDocument();

    fireEvent.keyDown(field, { key: "Enter", ctrlKey: true });
    await act(async () => {
      fireEvent.click(screen.getByTestId("maker-steps-save"));
    });

    expect(updateRecipeMutate).toHaveBeenCalledWith({
      recipeId: "r-1",
      data: { process_steps: [longStep] },
    });
  });

  it("cancels editing without saving", () => {
    renderTab();
    fireEvent.click(screen.getByTestId("maker-steps-edit"));
    fireEvent.change(screen.getByTestId("maker-steps-input"), {
      target: { value: "Unwanted step" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    fireEvent.click(screen.getByLabelText("Cancel"));

    expect(updateRecipeMutate).not.toHaveBeenCalled();
    // Read-only list is restored without the unsaved step.
    expect(screen.queryByText("Unwanted step")).not.toBeInTheDocument();
    expect(screen.getByText("Heat oven")).toBeInTheDocument();
  });

  it("labels the edit affordance so an empty recipe shows a way in", () => {
    renderTab({ process_steps: [] });
    expect(screen.getByTestId("maker-steps-edit")).toHaveTextContent(
      "Add steps",
    );
  });
});

describe("CompositionTab explains itself", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // These hints sit inside the manager's editing affordances, so the
    // account that can edit is the one that reads them.
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  /** The empty tab was the one screen with no answer to "what is this for?". */
  it("says what a BOM is while there is nothing else to read", () => {
    renderTab({ lines: [] });

    const intro = screen.getByTestId("maker-composition-intro");
    expect(intro).toHaveTextContent(/list of what goes into one batch/i);
    expect(intro).toHaveTextContent(/Cost & result/i);
  });

  it("gets out of the way once the first ingredient is there", () => {
    renderTab({ lines: [line] });

    expect(
      screen.queryByTestId("maker-composition-intro"),
    ).not.toBeInTheDocument();
  });

  /** The sentence was already written — as a comment nobody on screen reads. */
  it("says when the nested view is worth opening", () => {
    renderTab();

    expect(screen.getByTestId("maker-composition-tree-hint")).toHaveTextContent(
      /nested inside another/i,
    );
  });

  /**
   * The field answers "how much to reserve", and the question people bring to
   * it is "how much did I lose" — which is measured when the order is closed.
   */
  it("says the loss field is a planning figure and that zero is normal", () => {
    renderTab();
    fireEvent.click(screen.getByTestId("maker-composition-more-toggle"));

    const hint = screen.getByTestId("maker-composition-yield-hint");
    expect(hint).toHaveTextContent(/planning figure/i);
    expect(hint).toHaveTextContent(/Leaving it at 0 is normal/i);
    expect(screen.getByTestId("maker-composition-yield-input")).toHaveAttribute(
      "aria-describedby",
      hint.id,
    );
  });
});

describe("CompositionTab ingredient thumbnails", () => {
  it("shows the ingredient's picture when the product has one", () => {
    renderTab({
      lines: [
        { ...line, child_template_image_url: "https://img.example/oats.png" },
      ],
    });

    const img = screen.getByAltText("");
    expect(img).toHaveAttribute("src", "https://img.example/oats.png");
  });

  it("stays with the icon when the ingredient has no picture", () => {
    renderTab({ lines: [line] });

    expect(screen.queryByAltText("")).not.toBeInTheDocument();
  });
});
