import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RotationAnalysisCard from "./RotationAnalysisCard";
import enStats from "@/modules/stats/i18n/en.json";
import { tFor } from "@/test/mocks/i18n";
import type { RotationAnalysis } from "../types/analytics";

/**
 * The age tiles used to print "—" whenever nothing had been
 * consumed, on the strength of a guard whose premise no longer held —
 * stock age is measured from intake, so an intake-only organization
 * (everyone's first days) had a real number the screen refused to show,
 * two hundred pixels above a table showing it from the same payload.
 */
const base = {
  slow_movers: [],
  slow_movers_count: 0,
  slow_movers_value: 0,
  dead_stock: [],
  dead_stock_count: 0,
  dead_stock_value: 0,
  rotation_by_category: [],
} as unknown as RotationAnalysis;

// A real translator, not `(key) => key`: under the identity stub every
// assertion on a label asserts the key, and passes whether the translation
// exists or not.
const t = tFor("stats") as never;

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

function renderCard(data: Record<string, unknown>) {
  return render(
    wrap(
      <RotationAnalysisCard
        data={{ ...base, ...data } as unknown as RotationAnalysis}
        t={t}
      />,
    ),
  );
}

describe("RotationAnalysisCard", () => {
  it("shows the age the server computed, with zero consumption", () => {
    renderCard({
      average_stock_age_days: 2.5,
      median_stock_age_days: 2.5,
      consumed_items_count: 0,
    });

    expect(screen.getAllByText("2.5")).toHaveLength(2);
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("prints — only when there is nothing measurable to age", () => {
    renderCard({
      average_stock_age_days: null,
      median_stock_age_days: null,
      consumed_items_count: 0,
    });

    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  // The category row kept the truthiness guard the tiles had lost: a
  // server-sent 0.0 read as "no movement" while the same payload's tiles
  // printed 0.0 — one quantity, two sentences, two hundred pixels apart.
  it("prints a zero-day category age as the number it is", () => {
    renderCard({
      average_stock_age_days: 0.0,
      median_stock_age_days: 0.0,
      consumed_items_count: 0,
      rotation_by_category: [
        { category_name: "Uncategorized", average_days: 0.0, item_count: 568 },
      ],
    });

    // Two tiles plus the category row — the row's span carries the number
    // and the "days" suffix in one text run, hence the regex.
    expect(screen.getAllByText(/0\.0/)).toHaveLength(3);
    expect(
      screen.queryByText(enStats.analytics.rotation.noMovement),
    ).not.toBeInTheDocument();
  });

  it("says no movement for a category whose age is unknown", () => {
    renderCard({
      average_stock_age_days: 2.5,
      median_stock_age_days: 2.5,
      consumed_items_count: 1,
      rotation_by_category: [
        { category_name: "Dairy", average_days: null, item_count: 2 },
      ],
    });

    expect(screen.getByText(enStats.analytics.rotation.noMovement));
  });
});
