import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BomTreeEditor } from "./BomTreeEditor";
import { withLanguage } from "@/test/mocks/i18n";
import type { BomLine, BomTreeNode } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({
  useBomTree: vi.fn(),
  updateLine: vi.fn(),
  canManage: true,
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanManage: () => mocks.canManage,
}));

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useUpdateBomLine: () => ({ mutate: mocks.updateLine, isPending: false }),
}));

vi.mock("@/modules/maker/hooks/useBom", () => ({
  useBomTree: mocks.useBomTree,
  useMoveBomLine: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const line = (id: string): BomLine =>
  ({
    id,
    parent_template_id: "tpl-parent",
    child_template_id: `tpl-${id}`,
    child_template_name: `Ingredient ${id}`,
    qty_per_batch: "1",
    unit: "kg",
    uom_id: null,
    yield_loss_pct: "0",
    notes: null,
    parent_line_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  }) as unknown as BomLine;

function tree(...ids: string[]): BomTreeNode {
  return {
    line: null,
    children: ids.map((id) => ({ line: line(id), children: [] })),
  };
}

function renderTree(root: BomTreeNode) {
  mocks.useBomTree.mockReturnValue({
    data: { parent_template_id: "tpl-parent", root },
    isLoading: false,
    error: null,
  });
  return render(<BomTreeEditor templateId="tpl-parent" />);
}

describe("BomTreeEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // A product with variants has a formula per variant; the tree on one
  // variant's page asked for the product and got every variant's lines.
  it("reads the tree of the recipe it is given", () => {
    mocks.useBomTree.mockReturnValue({
      data: { parent_template_id: "tpl-parent", root: tree("a") },
      isLoading: false,
      error: null,
    });

    render(<BomTreeEditor templateId="tpl-parent" recipeId="recipe-variant" />);

    expect(mocks.useBomTree).toHaveBeenCalledWith(
      "tpl-parent",
      "recipe-variant",
    );
  });

  /**
   * The panel has no "below" of its own — ingredients are added in the
   * section above it, so the message points the reader at that section.
   */
  it("points at the section that actually adds ingredients", () => {
    renderTree(tree());

    expect(screen.getByText(/section above/i)).toBeInTheDocument();
    expect(screen.queryByText(/below/i)).not.toBeInTheDocument();
  });

  it("offers no drag instruction when there is nothing to drag", () => {
    renderTree(tree());

    expect(screen.queryByTestId("maker-tree-hint")).not.toBeInTheDocument();
  });

  it("offers none with a single row either — there is nothing to drop onto", () => {
    renderTree(tree("a"));

    expect(screen.queryByTestId("maker-tree-hint")).not.toBeInTheDocument();
  });

  it("offers it once two rows can be nested", () => {
    renderTree(tree("a", "b"));

    expect(screen.getByTestId("maker-tree-hint")).toBeInTheDocument();
  });

  it("writes row amounts with the translated unit, like the list beside it", async () => {
    // The tree said "2.5 pcs" while the flat list said "2,5 szt." — one
    // line's quantity, two dialects, same screen.
    mocks.useBomTree.mockReturnValue({
      data: {
        parent_template_id: "tpl-parent",
        root: {
          line: null,
          children: [
            {
              line: {
                ...line("a"),
                qty_per_batch: "2.5000",
                unit: "pcs",
              } as BomLine,
              children: [],
            },
          ],
        },
      },
      isLoading: false,
      error: null,
    });
    await withLanguage("pl", () => {
      render(<BomTreeEditor templateId="tpl-parent" />);

      expect(screen.getByText("2,5 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/2\.5\s+pcs/)).not.toBeInTheDocument();
    });
  });

  it("marks a line whose unit cannot be read as the stock unit", () => {
    renderTree({
      line: null,
      children: [
        {
          line: { ...line("a"), unit_mismatch: true } as BomLine,
          children: [],
        },
      ],
    });

    expect(screen.getByTestId("maker-tree-unit-mismatch")).toBeInTheDocument();
  });

  describe("an ingredient that has a BOM of its own", () => {
    const withSubAssembly = (over: Partial<BomLine>): BomTreeNode => ({
      line: null,
      children: [
        {
          line: {
            ...line("dough"),
            recipe_id: "recipe-bread",
            make_fresh: false,
            stock_on_hand: "3",
            ...over,
          } as BomLine,
          children: [{ line: line("flour"), children: [] }],
        },
      ],
    });

    it("says what the shelf holds of it, taken before it is made", () => {
      renderTree(withSubAssembly({}));

      expect(screen.getByTestId("maker-tree-on-hand")).toHaveTextContent(
        /3.* on hand/i,
      );
    });

    it("stops saying so once the line is made fresh every time", () => {
      renderTree(withSubAssembly({ make_fresh: true }));

      expect(screen.queryByTestId("maker-tree-on-hand")).toBeNull();
      expect(screen.getByLabelText(/always make fresh/i)).toBeChecked();
    });

    it("marks the line fresh on the recipe the line belongs to", () => {
      renderTree(withSubAssembly({}));

      fireEvent.click(screen.getByTestId("maker-tree-make-fresh-dough"));

      expect(mocks.updateLine.mock.calls[0][0]).toEqual({
        recipeId: "recipe-bread",
        lineId: "dough",
        data: { make_fresh: true },
      });
    });

    it("leaves the flag to the manager", () => {
      mocks.canManage = false;
      renderTree(withSubAssembly({}));

      expect(screen.getByTestId("maker-tree-make-fresh-dough")).toBeDisabled();
      mocks.canManage = true;
    });

    it("offers no toggle on a plain ingredient", () => {
      renderTree(tree("a"));

      expect(screen.queryByLabelText(/always make fresh/i)).toBeNull();
    });
  });
});
