import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { StatsCostAnalysis } from "./StatsCostAnalysis";
import type {
  CategoryCostItem,
  CostAnalysis,
} from "@/modules/stats/types/analytics";
import enStats from "@/modules/stats/i18n/en.json";
import { tFor } from "@/test/mocks/i18n";

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (value: number) => `${value.toFixed(2)} zł`,
}));

// A real translator, not `(key) => key`: under the identity stub every
// assertion on a label asserts the key, and passes whether the translation
// exists or not.
const t = tFor("stats") as never;

const unpricedSentence = (count: number) =>
  enStats.costAnalysis.categoryUnpriced_other.replace(
    "{{count}}",
    String(count),
  );

/**
 * The spent total is read off the valuation ledger; the category breakdown
 * is priced off the purchase price on each record, and a record without a
 * price counts toward the category but adds nothing to its sum. A card that
 * prints $352.80 over a category of $0.00 has to say where each figure
 * comes from, or the zero reads as "nothing was spent here".
 */
function analysis(
  categories: CategoryCostItem[],
  over: Partial<CostAnalysis> = {},
): CostAnalysis {
  return {
    total_spent: 352.8,
    total_wasted: 0,
    waste_value_percentage: 0,
    top_expensive_categories: categories,
    monthly_trend: [],
    savings_opportunities: [],
    excluded_other_currency_count: 0,
    ...over,
  } as CostAnalysis;
}

function category(over: Partial<CategoryCostItem> = {}): CategoryCostItem {
  return {
    category_name: "Other",
    category_code: null,
    total_spent: 0,
    total_wasted: 0,
    items_count: 4,
    value_source: "purchase_price",
    unpriced_count: 0,
    ...over,
  } as CategoryCostItem;
}

describe("StatsCostAnalysis — the breakdown names what it is priced from", () => {
  it("says the rows are priced off the purchase price on records", () => {
    render(<StatsCostAnalysis t={t} costAnalysis={analysis([category()])} />);
    expect(
      screen.getByText(enStats.costAnalysis.categoriesPricedFromRecords),
    ).toBeInTheDocument();
  });

  it("says the rows come from the cost ledger when they do", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis([
          category({ value_source: "valuation_layers" }),
        ])}
      />,
    );
    expect(
      screen.getByText(enStats.costAnalysis.categoriesPricedFromLedger),
    ).toBeInTheDocument();
  });

  it("names the category's unpriced positions instead of printing a bare zero", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis([
          category({ unpriced_count: 4, total_spent: 0 }),
        ])}
      />,
    );
    expect(screen.getByText(unpricedSentence(4))).toBeInTheDocument();
  });

  it("stays silent about unpriced positions when there are none", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis([category({ unpriced_count: 0 })])}
      />,
    );
    expect(screen.queryByText(unpricedSentence(0))).not.toBeInTheDocument();
  });

  it("every priced row still carries its source hint", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis([
          category({ total_spent: 40, items_count: 2 }),
          category({ category_name: "Tools", total_spent: 12, items_count: 1 }),
        ])}
      />,
    );
    expect(
      screen.getByText(enStats.costAnalysis.categoriesPricedFromRecords),
    ).toBeInTheDocument();
    expect(screen.queryByText(unpricedSentence(0))).not.toBeInTheDocument();
  });
});

/**
 * The two lists under the breakdown. They were only ever drawn from empty
 * arrays in the other specs, so a row that lost its amount or its month
 * would not have shown up anywhere.
 */
describe("StatsCostAnalysis — savings and the monthly trend", () => {
  it("lists each product that wasted money, with the amount and the advice", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis([category()], {
          savings_opportunities: [
            {
              product_name: "Fresh milk",
              category_name: "Dairy",
              category_code: null,
              wasted_amount: 12.5,
              suggestion: "Buy smaller packs",
            },
            {
              product_name: "Bread",
              category_name: "Bakery",
              category_code: null,
              wasted_amount: 3,
              suggestion: "Freeze half",
            },
          ] as never,
        })}
      />,
    );

    expect(
      screen.getByText(enStats.costAnalysis.savingsOpportunities),
    ).toBeInTheDocument();
    expect(screen.getByText("Fresh milk")).toBeInTheDocument();
    expect(screen.getByText("-12.50 zł")).toBeInTheDocument();
    expect(screen.getByText("Buy smaller packs")).toBeInTheDocument();
    expect(screen.getByText("Bread")).toBeInTheDocument();
    expect(screen.getByText("-3.00 zł")).toBeInTheDocument();
  });

  it("shows what was spent each month, and the waste only in months that had some", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis([category()], {
          monthly_trend: [
            { month: "2026-08", spent: 100, wasted: 0 },
            { month: "2026-09", spent: 80, wasted: 15 },
          ] as never,
        })}
      />,
    );

    expect(screen.getByText("2026-08")).toBeInTheDocument();
    expect(screen.getByText("100.00 zł")).toBeInTheDocument();
    expect(screen.getByText("2026-09")).toBeInTheDocument();
    expect(screen.getByText("80.00 zł")).toBeInTheDocument();
    expect(screen.getByText("-15.00 zł")).toBeInTheDocument();
    // The clean month prints no "-0.00".
    expect(screen.queryByText("-0.00 zł")).not.toBeInTheDocument();
  });
});
