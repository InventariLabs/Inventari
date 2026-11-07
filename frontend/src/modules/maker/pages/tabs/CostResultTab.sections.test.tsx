import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import { signInWith, signOut } from "@/test/auth";
import { CostResultTab } from "./CostResultTab";
import type {
  CostBreakdownResponse,
  MakerRecipe,
} from "@/modules/maker/types/maker";

// The lines editor is NOT mocked here: this file pins what the whole tab
// shows, which a test of the editor alone cannot (it never draws the label
// twice, whatever the tab around it does).
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

// The chart says nothing about the figures under test.
vi.mock("@/modules/maker/components/BreakdownPieChart", () => ({
  BreakdownPieChart: () => null,
}));

let breakdown: CostBreakdownResponse | undefined;
const costRead = vi.hoisted(() => ({ failed: false, refetch: vi.fn() }));

vi.mock("@/modules/maker/hooks/useBom", () => ({
  useBomCostEstimate: () => ({
    data: costRead.failed ? undefined : breakdown,
    isLoading: false,
    isError: costRead.failed,
    refetch: costRead.refetch,
  }),
}));

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
  useUpdateMakerRecipe: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAddCostLine: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateCostLine: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteCostLine: () => ({ mutate: vi.fn(), isPending: false }),
}));

const entry = {
  child_template_id: "tpl-oats",
  child_template_name: "Oats",
  consumed_qty: "2.000000",
  unit: "kg",
  unit_cost: null,
  cost: null,
  percentage_of_total: null,
  cost_source: "none",
};

const recipe: MakerRecipe = {
  id: "r-1",
  organization_id: "org-1",
  output_template_id: "tpl-1",
  name: "Granola Bars",
  batch_yield_qty: "5",
  batch_yield_uom_id: null,
  process_steps: null,
  reference_price: "9.00",
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

const withOneLine: MakerRecipe = {
  ...recipe,
  cost_lines: [
    {
      id: "cl-1",
      recipe_id: "r-1",
      kind: "LABOR",
      label: "Oven time",
      amount: "16.50",
      sort_order: 0,
    },
  ],
};

function renderTab(forRecipe: MakerRecipe) {
  render(
    <QueryWrapper>
      <CostResultTab recipe={forRecipe} />
    </QueryWrapper>,
  );
}

describe("CostResultTab — fixed costs", () => {
  beforeEach(() => {
    signInWith(["maker:read", "maker:write"]);
    breakdown = {
      output_template_id: "tpl-1",
      planned_qty: "1",
      total_cost: "0.00",
      entries: [entry],
      missing_cost_lines: ["tpl-oats"],
      recipe_state: "has_lines",
      recipe_id: "recipe-granola",
    };
  });

  afterEach(() => {
    signOut();
  });

  it("names the section once on the tab, not once on a summary card and once on the lines", () => {
    renderTab(withOneLine);

    expect(
      screen.getAllByRole("heading", { name: /fixed costs/i }),
    ).toHaveLength(1);
    expect(screen.getAllByText(/fixed costs/i)).toHaveLength(1);
  });

  it("prints a single line's amount once on the tab", () => {
    renderTab(withOneLine);

    expect(screen.getAllByText("PLN 16.50")).toHaveLength(1);
  });
});
