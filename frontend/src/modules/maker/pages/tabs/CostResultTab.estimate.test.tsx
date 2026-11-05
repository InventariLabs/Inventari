import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { signInWith, signOut } from "@/test/auth";
import { RecipeUnitCost } from "@/modules/maker/components/RecipeUnitCost";
import type {
  MakerRecipe,
  RecipeCatalogItem,
} from "@/modules/maker/types/maker";
import { CostResultTab } from "./CostResultTab";

// The chart says nothing about the figures under test.
vi.mock("@/modules/maker/components/BreakdownPieChart", () => ({
  BreakdownPieChart: () => null,
}));
vi.mock("@/modules/maker/components/CostLinesEditor", () => ({
  CostLinesEditor: () => null,
}));
vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
  useUpdateMakerRecipe: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

/**
 * One product, two formulas. Neither yield is 1, and none of the wrong
 * questions lands on the right figure: one unit of the default formula divided
 * by a yield gives 2.50 and 1.00, a batch of the wrong formula 5.00.
 */
const formulas: Record<
  string,
  { unitCost: number; batchYield: string; ingredient: string }
> = {
  default: { unitCost: 5, batchYield: "2", ingredient: "Oats" },
  variant: { unitCost: 1.25, batchYield: "5", ingredient: "Spelt" },
};

function recipeOf(id: keyof typeof formulas): MakerRecipe {
  return {
    id,
    organization_id: "org-1",
    output_template_id: "tpl-1",
    name: "Granola Bars",
    batch_yield_qty: formulas[id].batchYield,
    batch_yield_uom_id: null,
    process_steps: null,
    reference_price: null,
    is_default: id === "default",
    source_recipe_id: null,
    source_snapshot_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    output_template_name: "Granola Bars 500g",
    cost_lines: [],
    lines: [],
    estimated_unit_cost: null,
  };
}

/** What the catalogue's card is told about a formula. */
function catalogItemOf(id: keyof typeof formulas) {
  return {
    unit_cost: null,
    uncosted_ingredients: 0,
    estimated_unit_cost: formulas[id].unitCost.toFixed(2),
    estimated_uncosted_ingredients: 0,
  } as RecipeCatalogItem;
}

describe("CostResultTab — the estimate it asks for", () => {
  let asked: { path: string; params: Record<string, string> }[];

  beforeEach(() => {
    signInWith(["maker:read", "maker:write"]);
    asked = [];
    // Answers the way the endpoint does: the template's default formula and
    // one unit, unless the question names another formula or another amount.
    server.use(
      http.get("/api/v1/maker/bom/:templateId/cost-estimate", ({ request }) => {
        const url = new URL(request.url);
        const params = Object.fromEntries(url.searchParams);
        asked.push({ path: url.pathname, params });
        const qty = Number(params.qty ?? "1");
        const formula = formulas[params.recipe_id ?? "default"];
        const total = (formula.unitCost * qty).toFixed(2);
        return HttpResponse.json({
          output_template_id: "tpl-1",
          planned_qty: String(qty),
          total_cost: total,
          entries: [
            {
              child_template_id: `tpl-${formula.ingredient}`,
              child_template_name: formula.ingredient,
              consumed_qty: "1.000000",
              unit: "kg",
              unit_cost: total,
              cost: total,
              percentage_of_total: "100",
              cost_source: "avco",
            },
          ],
          missing_cost_lines: [],
          recipe_state: "has_lines",
          recipe_id: params.recipe_id ?? "default",
        });
      }),
    );
  });

  afterEach(() => {
    signOut();
  });

  function renderBeside(id: keyof typeof formulas) {
    render(
      <QueryWrapper>
        <div data-testid="card">
          <RecipeUnitCost recipe={catalogItemOf(id)} />
        </div>
        <div data-testid="tab">
          <CostResultTab recipe={recipeOf(id)} />
        </div>
      </QueryWrapper>,
    );
  }

  /** The figure printed right after the "Estimated unit cost" label. */
  const figureIn = (testId: string) =>
    within(screen.getByTestId(testId)).getByText("Estimated unit cost")
      .nextElementSibling?.textContent;

  it.each(["default", "variant"])(
    "asks about the %s formula itself, at a full batch",
    async (id) => {
      renderBeside(id);

      await waitFor(() => expect(asked).toHaveLength(1));
      expect(asked[0]).toEqual({
        path: "/api/v1/maker/bom/tpl-1/cost-estimate",
        params: { recipe_id: id, qty: formulas[id].batchYield },
      });
    },
  );

  it.each([
    ["default", /5[.,]00/],
    ["variant", /1[.,]25/],
  ])(
    "states the figure the catalogue's card states for the %s formula",
    async (id, figure) => {
      renderBeside(id);

      await within(screen.getByTestId("tab")).findByText(
        formulas[id].ingredient,
      );
      expect(figureIn("card")).toMatch(figure);
      expect(figureIn("tab")).toBe(figureIn("card"));
    },
  );

  it("lists the variant's own ingredients, not the default formula's", async () => {
    renderBeside("variant");

    const tab = within(screen.getByTestId("tab"));
    expect(await tab.findByText("Spelt")).toBeInTheDocument();
    expect(tab.queryByText("Oats")).toBeNull();
  });
});
