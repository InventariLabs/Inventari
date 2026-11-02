import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import { signInWith, signOut } from "@/test/auth";
import { CostResultTab } from "./CostResultTab";
import { withLanguage } from "@/test/mocks/i18n";
import type {
  CostBreakdownResponse,
  MakerRecipe,
} from "@/modules/maker/types/maker";

// The chart says nothing about the figures under test.
vi.mock("@/modules/maker/components/BreakdownPieChart", () => ({
  BreakdownPieChart: () => null,
}));

vi.mock("@/modules/maker/components/CostLinesEditor", () => ({
  CostLinesEditor: () => null,
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

function renderTab() {
  render(
    <QueryWrapper>
      <CostResultTab recipe={recipe} />
    </QueryWrapper>,
  );
}

describe("CostResultTab when nobody has priced the ingredients", () => {
  beforeEach(() => {
    signInWith(["maker:read", "maker:write"]);
    breakdown = {
      output_template_id: "tpl-1",
      planned_qty: "1",
      total_cost: "0.00",
      entries: [entry, { ...entry, child_template_id: "tpl-honey" }],
      missing_cost_lines: ["tpl-oats", "tpl-honey"],
      recipe_state: "has_lines",
      recipe_id: "recipe-granola",
    };
  });

  afterEach(() => {
    signOut();
  });

  it("refuses a unit cost instead of announcing zero", () => {
    // Measured: the ingredient row read "—" and the tile above it read
    // "$0.00 · per unit", while the REFERENCE PRICE tile beside it answered
    // the same kind of gap with "—".
    renderTab();

    // Scoped to the tile: the fixed-cost total lives in the section below
    // (inside the lines editor), so this tile is the only figure here.
    // The tile names the figure an estimate: layer rates today, not a
    // run's measurement — the same word the catalog card uses.
    const tile = screen.getByText("Estimated unit cost").closest("div");
    expect(tile).not.toBeNull();
    expect(tile?.textContent).not.toMatch(/0[.,]00/);
    expect(tile?.textContent).toContain("—");
  });

  it("says how many ingredients the figure is missing", () => {
    renderTab();

    expect(
      screen.getAllByText(
        "No rate for any of the 2 ingredients — there is nothing to add up.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("does not compute savings against a cost it refused to state", () => {
    renderTab();

    expect(screen.queryByText(/Savings vs shop price:/)).toBeNull();
  });
});

describe("CostResultTab when some ingredients are priced", () => {
  beforeEach(() => {
    signInWith(["maker:read", "maker:write"]);
    breakdown = {
      output_template_id: "tpl-1",
      planned_qty: "1",
      total_cost: "10.00",
      entries: [
        { ...entry, unit_cost: "5.00", cost: "10.00", cost_source: "avco" },
        { ...entry, child_template_id: "tpl-honey" },
      ],
      missing_cost_lines: ["tpl-honey"],
      recipe_state: "has_lines",
      recipe_id: "recipe-granola",
    };
  });

  afterEach(() => {
    signOut();
  });

  it("keeps the partial total and marks what it leaves out", () => {
    renderTab();

    expect(screen.getAllByText(/10[.,]00/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        "1 ingredient has no rate, so it is missing from this figure.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("still states the savings, because the cost is a figure", () => {
    renderTab();

    // 9.00 reference − 10.00/5 unit cost = 7.00 saved per unit.
    expect(screen.getByText(/Savings vs shop price:/)).toBeInTheDocument();
  });

  it("names ingredient amounts in the reader's unit language", async () => {
    // The cost tab kept its own convention: a raw symbol ("1 pcs") where
    // the shelf list next to it says "1 szt.". One formatter, one word.
    breakdown = {
      output_template_id: "tpl-1",
      planned_qty: "1",
      total_cost: "10.00",
      entries: [
        {
          ...entry,
          consumed_qty: "1.000000",
          unit: "pcs",
          unit_cost: "5.00",
          cost: "10.00",
          cost_source: "avco",
        },
      ],
      missing_cost_lines: [],
      recipe_state: "has_lines",
      recipe_id: "recipe-granola",
    };
    await withLanguage("pl", () => {
      renderTab();

      expect(screen.getByText("1 szt.")).toBeInTheDocument();
      expect(screen.queryByText(/1 pcs/)).not.toBeInTheDocument();
    });
  });
});

describe("CostResultTab when the estimate did not load", () => {
  beforeEach(() => {
    signInWith(["maker:read", "maker:write"]);
    costRead.failed = true;
    costRead.refetch.mockClear();
  });

  afterEach(() => {
    costRead.failed = false;
    signOut();
  });

  it("says so, with a retry, instead of leaving the breakdown out", () => {
    renderTab();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(costRead.refetch).toHaveBeenCalledTimes(1);
  });
});
