import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { StatsCostAnalysis } from "./StatsCostAnalysis";
import type { CostAnalysis } from "@/modules/stats/types/analytics";
import enStats from "@/modules/stats/i18n/en.json";
import { tFor, withLanguage } from "@/test/mocks/i18n";

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (value: number) => `${value.toFixed(2)} zł`,
}));

// A real translator, not `(key) => key`: under the identity stub every
// assertion on a label asserts the key, and passes whether the translation
// exists or not.
const t = tFor("stats") as never;

/**
 * "Nothing was thrown away" and "we were not counting yet" are different
 * answers, and this screen used to give the first for both: a confident
 * 0.00 over a month of waste. An outflow is priced when it happens; for a
 * window from before the ledger kept that price there is nothing to read,
 * and today's average was not the average then.
 */
function analysis(over: Partial<CostAnalysis> = {}): CostAnalysis {
  return {
    total_spent: 120,
    total_wasted: 25,
    waste_value_percentage: 20.8,
    top_expensive_categories: [],
    monthly_trend: [],
    savings_opportunities: [],
    excluded_other_currency_count: 0,
    ...over,
  } as CostAnalysis;
}

describe("StatsCostAnalysis — an unpriced window says so", () => {
  it("shows the amount when the ledger has one", () => {
    render(<StatsCostAnalysis t={t} costAnalysis={analysis()} />);
    expect(screen.getByText("25.00 zł")).toBeInTheDocument();
    expect(screen.getByText("20.8%")).toBeInTheDocument();
  });

  /**
   * `waste_value_percentage` is read off the wire, so it used to be printed
   * as JavaScript writes numbers: a fractional percent showed a dot on a
   * Polish screen.
   */
  it("writes the waste percent the way the reader's language does", async () => {
    await withLanguage("pl", () => {
      render(<StatsCostAnalysis t={t} costAnalysis={analysis()} />);
      expect(screen.getByText("20,8%")).toBeInTheDocument();
    });
  });

  it("does not print a zero it cannot stand behind", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis({
          total_wasted: null,
          waste_value_percentage: null,
        })}
      />,
    );
    expect(screen.queryByText("0.00 zł")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("says why the figure is missing", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis({
          total_wasted: null,
          waste_value_percentage: null,
        })}
      />,
    );
    expect(
      screen.getByText(enStats.costAnalysis.notValuedYet),
    ).toBeInTheDocument();
  });

  it("leaves the spend alone — that one is always answerable", () => {
    render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis({
          total_wasted: null,
          waste_value_percentage: null,
        })}
      />,
    );
    expect(screen.getByText("120.00 zł")).toBeInTheDocument();
  });

  it("renders nothing where the profile does not show stock value", () => {
    // Every figure here is money, so a profile that turned the value signal
    // off gets no section rather than a heading over withheld numbers.
    const { container } = render(
      <StatsCostAnalysis
        t={t}
        costAnalysis={analysis()}
        showInventoryValue={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
