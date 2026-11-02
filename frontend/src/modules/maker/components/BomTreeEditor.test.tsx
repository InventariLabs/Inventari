import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { BomTreeEditor } from "./BomTreeEditor";
import { withLanguage } from "@/test/mocks/i18n";
import type { BomLine, BomTreeNode } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({
  useBomTree: vi.fn(),
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

  /**
   * The panel has no "below" of its own — ingredients are added in the
   * section above it, and the message used to send the reader looking for a
   * form that is not in this card.
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
});
