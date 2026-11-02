import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ProductionPreviewSheet } from "./ProductionPreviewSheet";
import { QueryWrapper } from "@/test/queryWrapper";
import { withLanguage } from "@/test/mocks/i18n";
import { signInWith } from "@/test/auth";
import type { CostBreakdownResponse } from "@/modules/maker/types/maker";

// The pie chart is irrelevant for this test — keep it out of the render tree.
vi.mock("./BreakdownPieChart", () => ({
  BreakdownPieChart: () => null,
}));

const breakdown: CostBreakdownResponse = {
  output_template_id: "tpl-jam",
  planned_qty: "4",
  total_cost: "10.00",
  recipe_state: "has_lines",
  recipe_id: "recipe-jam",
  entries: [
    {
      child_template_id: "7e92e269-03c1-4b0f-9a11-abcdefabcdef",
      child_template_name: "E2E-Result-Fruit",
      consumed_qty: "4.000000",
      unit: "kg",
      unit_cost: "2.50",
      cost: "10.00",
      percentage_of_total: "100.00",
      cost_source: "avco",
    },
  ],
  missing_cost_lines: [],
};

function renderSheet(
  props: Partial<React.ComponentProps<typeof ProductionPreviewSheet>> = {},
) {
  render(
    <MemoryRouter>
      <QueryWrapper>
        <ProductionPreviewSheet
          open
          onClose={() => {}}
          breakdown={breakdown}
          isLoading={false}
          error={null}
          {...props}
        />
      </QueryWrapper>
    </MemoryRouter>,
  );
}

describe("ProductionPreviewSheet", () => {
  it("renders the ingredient display name, not a truncated UUID", () => {
    renderSheet();
    expect(screen.getByText("E2E-Result-Fruit")).toBeInTheDocument();
    expect(screen.queryByText(/7e92e269/)).not.toBeInTheDocument();
  });

  it("prices the amounts instead of printing what the API sent", () => {
    // "10.00" is a string from the wire: an American point, no currency, and
    // the same figure written "10,00 zł" on the tab next door.
    renderSheet();
    expect(screen.queryAllByText("10.00")).toHaveLength(0);
    expect(screen.getAllByText(/10[.,]00\s*\S+/).length).toBeGreaterThan(0);
  });

  it("says a formula with no ingredients is empty instead of costing 0.00", () => {
    renderSheet({
      breakdown: {
        ...breakdown,
        entries: [],
        total_cost: "0.00",
        recipe_state: "empty",
        recipe_id: "recipe-jam",
      },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/no ingredients/i);
    expect(screen.queryByText(/^0[.,]00/)).not.toBeInTheDocument();
    // The empty truth leads to the formula it is about, not just away from
    // the sheet.
    expect(
      screen.getByRole("link", { name: /add ingredients/i }),
    ).toHaveAttribute("href", "/maker/recipes/recipe-jam");
  });

  it("says a product with no formula has no formula, and leads to creating one", () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    // The two zero-entry truths are different sentences with different
    // doors: this one claims no recipe exists (the create button's own
    // answer), not that one waits empty.
    let seen: unknown;
    const Probe = () => {
      seen = useLocation().state;
      return null;
    };
    render(
      <MemoryRouter initialEntries={["/maker/production"]}>
        <Probe />
        <QueryWrapper>
          <ProductionPreviewSheet
            open
            onClose={() => {}}
            breakdown={{
              ...breakdown,
              entries: [],
              total_cost: "0.00",
              recipe_state: "no_recipe",
              recipe_id: null,
            }}
            isLoading={false}
            error={null}
            outputProduct={{
              product_template_id: "tpl-jam",
              name: "Jam",
              sku: null,
              barcode: null,
              brand: null,
              uom_id: null,
              uom_symbol: null,
              image_url: null,
              is_stub: false,
            }}
          />
        </QueryWrapper>
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/no BOM/i);
    expect(screen.queryByText(/no ingredients/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("missing-recipe-create-link"));

    expect(seen).toEqual({
      createRecipeFor: expect.objectContaining({
        product_template_id: "tpl-jam",
      }),
    });
  });

  it("refuses the total instead of announcing zero above its own warning", () => {
    // Measured on the sheet, one under the other: "TOTAL COST 0.00 USD", an
    // amber note saying no ingredient has a rate, and an ingredient row of
    // "—". The window knew, said so, and still answered zero.
    renderSheet({
      breakdown: {
        ...breakdown,
        total_cost: "0.00",
        entries: [
          {
            ...breakdown.entries[0],
            unit_cost: null,
            cost: null,
            percentage_of_total: null,
            cost_source: "none",
          },
        ],
        missing_cost_lines: [breakdown.entries[0].child_template_id],
      },
    });

    const tile = screen.getByText("Total cost").parentElement;
    expect(tile?.textContent).not.toMatch(/0[.,]00/);
    expect(tile?.textContent).toContain("—");
  });

  it("counts the ingredients with no rate in words, not as a bare number", () => {
    renderSheet({
      breakdown: {
        ...breakdown,
        total_cost: "10.00",
        entries: [
          breakdown.entries[0],
          {
            ...breakdown.entries[0],
            child_template_id: "tpl-honey",
            child_template_name: "Honey",
            unit_cost: null,
            cost: null,
            percentage_of_total: null,
            cost_source: "none",
          },
        ],
        missing_cost_lines: ["tpl-honey"],
      },
    });

    // Exactly once in the accessibility tree: the amber card carries the
    // sentence visibly, so the figure above must not repeat it to a screen
    // reader through its own sr-only copy.
    expect(
      screen.getAllByText(
        "1 ingredient has no rate, so it is missing from this figure.",
      ).length,
    ).toBe(1);
    // The old line pasted the count after a sentence ending in a colon and a
    // zero — "These contribute 0 to cost: 1".
    expect(screen.queryByText(/contribute 0 to cost/)).toBeNull();
  });

  it("falls back to the truncated UUID when the template was deleted", () => {
    renderSheet({
      breakdown: {
        ...breakdown,
        entries: [{ ...breakdown.entries[0], child_template_name: null }],
      },
    });
    expect(screen.getByText(/7e92e269…/)).toBeInTheDocument();
  });
});

describe("ProductionPreviewSheet — quantities", () => {
  it("prints the quantity the reader writes, not the padding the wire sent", () => {
    // The preview used to echo `consumed_qty` raw: "50.00000 pcs" next to
    // a cost rounded to two places. The shared formatter strips the
    // column's padding; this pins that the strip reaches this panel.
    renderSheet();

    expect(screen.getByText(/4 kg/)).toBeInTheDocument();
    expect(screen.queryByText(/4\.000000/)).not.toBeInTheDocument();
  });

  it("writes header and ingredient amounts by one convention, separator included", async () => {
    // The header said "Ilość: 10 000 kg" while its own ingredient list said
    // "22000 kg" — two grouping decisions inside one panel. Quantities group
    // thousands on every screen, and both lines come from one formatter.
    await withLanguage("pl", () => {
      renderSheet({
        breakdown: {
          ...breakdown,
          planned_qty: "10000.000",
          planned_uom_symbol: "kg",
          entries: [
            { ...breakdown.entries[0], consumed_qty: "22000.000", unit: "kg" },
          ],
        },
      });

      expect(screen.getByText(/Ilość: 10 000 kg/)).toBeInTheDocument();
      expect(screen.getByText("22 000 kg")).toBeInTheDocument();
      expect(screen.queryByText(/10000|22000/)).not.toBeInTheDocument();
    });
  });

  it("writes the header unit in the reader's language, not the wire's", async () => {
    await withLanguage("pl", () => {
      renderSheet({
        breakdown: {
          ...breakdown,
          planned_qty: "4.000",
          planned_uom_symbol: "pcs",
          entries: [
            { ...breakdown.entries[0], consumed_qty: "4.000", unit: "pcs" },
          ],
        },
      });

      expect(screen.getByText(/Ilość: 4 szt\./)).toBeInTheDocument();
      expect(screen.getByText("4 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/4 pcs/)).not.toBeInTheDocument();
    });
  });
});
