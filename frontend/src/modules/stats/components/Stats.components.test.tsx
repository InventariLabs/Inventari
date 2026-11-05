import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

import { StatsOverviewCards } from "@/modules/stats/components/StatsOverviewCards";
import { StatsHealthCard } from "@/modules/stats/components/StatsHealthCard";
import { StatsDistributionGrid } from "@/modules/stats/components/StatsDistributionGrid";
import { StatsExpiryForecast } from "@/modules/stats/components/StatsExpiryForecast";
import ExpenseForecastChart from "@/modules/stats/components/ExpenseForecastChart";
import SmartAlertsPanel from "@/modules/stats/components/SmartAlertsPanel";
import RotationAnalysisCard from "@/modules/stats/components/RotationAnalysisCard";
import PurchasePatternsGrid from "@/modules/stats/components/PurchasePatternsGrid";
import StatsOverviewTab from "@/modules/stats/components/StatsOverviewTab";

import type {
  AttentionCounts,
  OverviewStats,
  StorageStats,
  CategoryStats,
  ExpiryForecast,
} from "@/types";
import type {
  SmartAlerts,
  RotationAnalysis,
  PurchasePatterns,
  ExpenseForecast,
  CostAnalysis,
} from "@/modules/stats/types/analytics";
import enStats from "@/modules/stats/i18n/en.json";
import { tFor, withLanguage } from "@/test/mocks/i18n";

// The money components read the organization's currency themselves instead of
// being handed it — a prop nobody passed is how "0.00 ?" reached the screen.
// Tests drive it from here.
let orgCurrency: string | undefined = "PLN";
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => orgCurrency,
}));

// ── helpers ───────────────────────────────────────────────────────────────────

// Real translator bound to the page namespace; stats falls back to common.
const t = tFor("stats");

const wrap = (el: React.ReactElement) => <MemoryRouter>{el}</MemoryRouter>;

// ── fixtures ──────────────────────────────────────────────────────────────────

const overview: OverviewStats = {
  total_items: 50,
  total_locations: 4,
  expiring_soon: 3,
  expired: 1,
  low_stock: 5,
  total_value: 1250.5,
  value_source: "valuation_layers",
  value_scope: "organization",
  excluded_other_currency_count: 0,
  unvalued_stock_count: 0,
  unpriced_item_count: 0,
  value_known: true,
  tracks_expiry: true,
};

/** The one count both screens read — see `useAttentionCounts`. */
const attentionCounts: AttentionCounts = {
  records: 0,
  expired: 1,
  expiring_soon: 3,
  low_stock: 5,
};

const storageStats: StorageStats[] = [
  {
    location_id: "s1",
    location_name: "Fridge",
    location_type: "fridge",
    items_count: 20,
    expiring_soon: 2,
  },
  {
    location_id: "s2",
    location_name: "Pantry",
    location_type: "shelf",
    items_count: 30,
    expiring_soon: 1,
  },
];

const categoryStats: CategoryStats[] = [
  {
    unpriced_count: 0,
    value_source: "purchase_price",
    category_id: "c1",
    category_name: "Dairy",
    category_code: "DAI",
    category_icon: null,
    items_count: 10,
    total_value: 50,
  },
  {
    unpriced_count: 0,
    value_source: "purchase_price",
    category_id: "c2",
    category_name: "Veggies",
    category_code: "VEG",
    category_icon: null,
    items_count: 15,
    total_value: 30,
  },
];

const expiryForecast: ExpiryForecast[] = [
  { period: "Expired", count: 1 },
  { period: "Today", count: 2 },
  { period: "This week", count: 5 },
];

// The three alerts the backend produces, each in the shape it sends.
const smartAlerts: SmartAlerts = {
  total_alerts: 4,
  alerts: [
    {
      type: "EXPIRED",
      severity: "critical",
      item_id: "cheddar-id",
      item_name: "Cheddar",
      expiry_date: "2026-10-29",
      days_until_expiry: -2,
      message_key: "stats.alerts.expired",
      message_params: { product: "Cheddar", days: -2, date: "29.10.2026" },
      action: "view_item",
      action_param: "cheddar-id",
    },
    {
      type: "EXPIRING_SOON",
      severity: "warning",
      item_id: "milk-id",
      item_name: "Milk",
      action: "view_item",
      action_param: "milk-id",
      expiry_date: "2026-11-02",
      days_until_expiry: 2,
      message_key: "stats.alerts.expiring_soon",
      message_params: { product: "Milk", days: 2, date: "02.11.2026" },
    },
    {
      type: "FORGOTTEN_ITEM",
      severity: "warning",
      item_name: "Bread",
      days_untouched: 75,
      message_key: "stats.alerts.forgotten_item",
      message_params: { product: "Bread", days: 75 },
    },
    {
      type: "MISSING_STAPLE",
      severity: "info",
      item_name: "Coffee",
      message_key: "stats.alerts.missing_staple",
      message_params: { product: "Coffee", frequency: 7, days_since: 22 },
    },
  ],
};

const rotationAnalysis: RotationAnalysis = {
  value_source: "purchase_price",
  average_stock_age_days: 14.5,
  median_stock_age_days: 12,
  consumed_items_count: 9,
  slow_movers_count: 3,
  slow_movers_value: 42.0,
  dead_stock_count: 1,
  dead_stock_value: 15.5,
  slow_movers: [],
  dead_stock: [],
  rotation_by_category: [
    { category_name: "Dairy", item_count: 5, average_days: 7 },
  ],
};

const expenseForecast: ExpenseForecast = {
  value_source: "valuation_layers",
  forecast_period: "month",
  predicted_spending: 180,
  historical_avg: 160,
  trend: "increasing",
  trend_percentage: 12.5,
  top_cost_drivers: [],
  waste_reduction_potential: 20,
  confidence: 0.75,
  weeks_of_data: 9,
  weeks_required: 6,
};

const purchasePatterns: PurchasePatterns = {
  value_source: "purchase_price",
  top_recurring_products: [
    {
      name: "Milk",
      brand: "FarmFresh",
      category: "Dairy",
      purchase_frequency_days: 14,
      total_purchases_last_6_months: 12,
      avg_price: 2.5,
      avg_quantity: 1,
      total_spent: 30,
      price_volatility: "stable",
    },
  ],
  seasonal_products: [
    {
      name: "Strawberries",
      peak_month: "June",
      peak_quantity: 5,
      average_quantity: 2,
      seasonality_score: 0.8,
      peak_months: ["June"],
      avg_monthly_spend_peak: 24,
      avg_monthly_spend_off_season: 6,
    },
  ],
  bulk_opportunities: [
    {
      product: "Rice",
      brand: undefined,
      current_avg_purchase_kg: 1,
      current_price_per_kg: 3,
      bulk_option_kg: 5,
      bulk_price_per_kg: 2.4,
      unit_price_current: 3,
      potential_annual_savings: 15,
    },
  ],
};

const costAnalysis: CostAnalysis = {
  total_spent: 120,
  total_wasted: 25,
  waste_value_percentage: 20.8,
  top_expensive_categories: [],
  monthly_trend: [],
  savings_opportunities: [],
  excluded_other_currency_count: 0,
  value_source: "valuation_layers",
};

// ── StatsOverviewCards ────────────────────────────────────────────────────────

describe("StatsOverviewCards", () => {
  it("renders total_items count", () => {
    render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={overview}
          attentionCounts={attentionCounts}
        />,
      ),
    );
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("calls the row count records, as the products list does", () => {
    // total_items counts stock rows, so a product held as two rows is two
    // of them; the tile used to call that number "Products".
    render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={overview}
          attentionCounts={attentionCounts}
        />,
      ),
    );
    expect(screen.getByText("Records")).toBeInTheDocument();
    expect(screen.queryByText("Products")).toBeNull();
  });

  it("offers no expiry tiles where the workspace keeps no dates", () => {
    // One decision for the whole screen: these two used to be unconditional,
    // so the card above could say "you keep no dates" while the tiles one
    // click lower answered "0 expiring, 8 expired".
    const { rerender } = render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={overview}
          attentionCounts={attentionCounts}
          tracksExpiry
        />,
      ),
    );
    expect(screen.getByText("3")).toBeInTheDocument();

    rerender(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={overview}
          attentionCounts={attentionCounts}
          tracksExpiry={false}
        />,
      ),
    );
    expect(screen.queryByText("3")).not.toBeInTheDocument();
    // The neutral tiles stay.
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("renders total_locations count", () => {
    render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={overview}
          attentionCounts={attentionCounts}
        />,
      ),
    );
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("renders the expiry tiles from the one count, not the overview", () => {
    // The tiles used to read `overview`, the second computation the health
    // card above had just stopped reading. A number only in the overview
    // must not appear here.
    render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={{ ...overview, expiring_soon: 99, expired: 88 }}
          attentionCounts={attentionCounts}
          tracksExpiry
        />,
      ),
    );
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.queryByText("99")).not.toBeInTheDocument();
    expect(screen.queryByText("88")).not.toBeInTheDocument();
  });

  it("renders zero values when overview has zeros", () => {
    const empty: OverviewStats = {
      total_items: 0,
      total_locations: 0,
      expiring_soon: 0,
      expired: 0,
      low_stock: 0,
      total_value: 0,
      value_source: "purchase_price",
      value_scope: "locations",
      excluded_other_currency_count: 0,
      unvalued_stock_count: 0,
      unpriced_item_count: 0,
      value_known: true,
      tracks_expiry: false,
    };
    render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={empty}
          attentionCounts={{
            expired: 0,
            expiring_soon: 0,
            low_stock: 0,
            records: 0,
          }}
        />,
      ),
    );
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
  });

  it("links into the inventory module, not to its redirect aliases", () => {
    render(
      wrap(
        <StatsOverviewCards
          t={t}
          overview={overview}
          attentionCounts={attentionCounts}
        />,
      ),
    );
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/inventory/items");
    expect(hrefs).toContain("/inventory/locations");
  });
});

// ── StatsHealthCard ───────────────────────────────────────────────────────────

describe("StatsHealthCard", () => {
  const defaultProps = {
    t,
    needsAttentionCount: 4,
    lowStockCount: 2,
    totalInventoryValue: 1234.5,
    showDetails: false,
    onToggleDetails: vi.fn(),
  };

  it("signs the value tile with the icon of the currency in use", () => {
    // The tile carried a fixed icon, so a złoty total sat next to whatever
    // glyph the component happened to import.
    orgCurrency = "USD";
    const { container, rerender } = render(
      wrap(<StatsHealthCard {...defaultProps} />),
    );
    expect(container.querySelector(".lucide-dollar-sign")).toBeTruthy();

    orgCurrency = "EUR";
    rerender(wrap(<StatsHealthCard {...defaultProps} />));
    expect(container.querySelector(".lucide-euro")).toBeTruthy();
    expect(container.querySelector(".lucide-dollar-sign")).toBeNull();
    orgCurrency = "PLN";
  });

  it("says the value is a lower bound when receipts on the shelf were never priced", () => {
    const { rerender } = render(wrap(<StatsHealthCard {...defaultProps} />));
    expect(
      screen.queryByText(/posted without a price/),
    ).not.toBeInTheDocument();

    rerender(
      wrap(<StatsHealthCard {...defaultProps} unvaluedStockCount={3} />),
    );
    expect(
      screen.getByText(/Receipts in stock posted without a price: 3/),
    ).toBeInTheDocument();
  });

  it("opens the records the needs-attention number counts", () => {
    render(wrap(<StatsHealthCard {...defaultProps} />));
    const tile = screen.getByText("4").closest("a");
    expect(tile).toHaveAttribute(
      "href",
      "/inventory/items?filter=needs-attention",
    );
  });

  it("reads a value nobody priced as unknown, not as zero", () => {
    render(
      wrap(<StatsHealthCard {...defaultProps} totalInventoryValue={null} />),
    );
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(
      screen.getByText(/No product here has a price yet/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0[.,]00/)).not.toBeInTheDocument();
  });

  it("calls no unknown value a lower bound", () => {
    render(
      wrap(
        <StatsHealthCard
          {...defaultProps}
          totalInventoryValue={null}
          unvaluedStockCount={6}
          unpricedItemCount={6}
        />,
      ),
    );
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.queryByText(/lower bound/)).not.toBeInTheDocument();
  });

  it("says the value is a lower bound when some records carry no price", () => {
    const { rerender } = render(wrap(<StatsHealthCard {...defaultProps} />));
    expect(
      screen.queryByText(/Records without a price/),
    ).not.toBeInTheDocument();

    rerender(wrap(<StatsHealthCard {...defaultProps} unpricedItemCount={5} />));
    expect(
      screen.getByText(
        "Records without a price: 5. This value is a lower bound.",
      ),
    ).toBeInTheDocument();
  });

  it("renders needsAttentionCount", () => {
    render(wrap(<StatsHealthCard {...defaultProps} />));
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("captions the needs-attention tile with what it counts", () => {
    render(wrap(<StatsHealthCard {...defaultProps} />));
    // The rows the list opens with, and nothing the number does not contain
    // ("requiring review" used to be named here and counted nowhere).
    expect(
      screen.getByText(
        "Records expired or expiring soon, and every record of a product running low.",
      ),
    ).toBeInTheDocument();
  });

  it("says the running-low tile counts products, inside the other tile's records", () => {
    render(wrap(<StatsHealthCard {...defaultProps} />));
    expect(
      screen.getByText(
        "Products at or below their threshold. Their records also count in Needs Attention.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the age the server sent even where nothing has moved", () => {
    // Stock age is measured from intake, so zero consumption is not
    // a reason to hide it — the guard used to print "—" over a computed,
    // sent number. "—" now means only what the server's null means:
    // nothing measurable stands on any shelf.
    const { rerender } = render(
      wrap(<RotationAnalysisCard data={rotationAnalysis} t={t} />),
    );
    expect(screen.getByText("14.5")).toBeInTheDocument();

    rerender(
      wrap(
        <RotationAnalysisCard
          data={{
            ...rotationAnalysis,
            consumed_items_count: 0,
            average_stock_age_days: 0,
            median_stock_age_days: 0,
          }}
          t={t}
        />,
      ),
    );
    // Fresh stock on the shelf is 0.0 days old — the truth, however small.
    expect(screen.getAllByText("0.0").length).toBeGreaterThan(0);

    rerender(
      wrap(
        <RotationAnalysisCard
          data={{
            ...rotationAnalysis,
            consumed_items_count: 0,
            average_stock_age_days: null,
            median_stock_age_days: null,
          }}
          t={t}
        />,
      ),
    );
    expect(screen.getAllByText("\u2014").length).toBeGreaterThan(0);
  });

  it("counts the signals it actually shows", () => {
    // The sentence read "Three signals" whatever the grid held, and a
    // workspace that keeps no dates was shown two. The count is the grid:
    // needs attention + running low, plus the value where the profile
    // keeps it.
    const { rerender } = render(wrap(<StatsHealthCard {...defaultProps} />));
    expect(screen.getByText(/3 signals/i)).toBeInTheDocument();

    rerender(
      wrap(<StatsHealthCard {...defaultProps} showInventoryValue={false} />),
    );
    expect(screen.getByText(/2 signals/i)).toBeInTheDocument();
    expect(screen.queryByText(/3 signals/i)).not.toBeInTheDocument();
  });

  it("renders lowStockCount", () => {
    render(wrap(<StatsHealthCard {...defaultProps} />));
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders totalInventoryValue formatted", () => {
    const { container } = render(wrap(<StatsHealthCard {...defaultProps} />));
    // Intl-format may include commas (e.g. "1,234.50") that split the text
    // across nodes; assert substring match against the rendered HTML.
    expect(container.textContent ?? "").toMatch(/1,234/);
  });

  // The home profile presets `show_inventory_value` off: the value
  // is a business metric, and a home pantry keeps no cost ledger behind it.
  it("drops the value signal when the profile presets it off", () => {
    const { container } = render(
      wrap(<StatsHealthCard {...defaultProps} showInventoryValue={false} />),
    );
    // The questions a home pantry asks stay; the business metric goes.
    expect(container.textContent ?? "").not.toMatch(/1,234/);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    // ...and the subtitle counts the two signals that remain.
    expect(screen.getByText(/2 signals/i)).toBeInTheDocument();
  });

  it("keeps the value signal when the setting is on", () => {
    const { container } = render(
      wrap(<StatsHealthCard {...defaultProps} showInventoryValue={true} />),
    );
    expect(container.textContent ?? "").toMatch(/1,234/);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText(/3 signals/i)).toBeInTheDocument();
  });

  it("calls onToggleDetails when toggle button clicked", () => {
    const onToggle = vi.fn();
    render(
      wrap(<StatsHealthCard {...defaultProps} onToggleDetails={onToggle} />),
    );
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalledOnce();
  });
});

// ── StatsDistributionGrid ─────────────────────────────────────────────────────

describe("StatsDistributionGrid", () => {
  const props = {
    t,
    storageStats,
    maxStorageCount: 30,
    categoryStats,
    maxCategoryCount: 15,
  };

  it("renders storage names", () => {
    render(<StatsDistributionGrid {...props} />);
    expect(screen.getByText("Fridge")).toBeInTheDocument();
    expect(screen.getByText("Pantry")).toBeInTheDocument();
  });

  it("writes a name as its owner did, so its word space stays visible", () => {
    // Between capitals the font's narrow space closed "RACK A-01" to
    // "RACKA-01", typed that way or set in capitals here. jsdom lays nothing
    // out, so this pins the rule; the gap itself was measured in a browser.
    render(<StatsDistributionGrid {...props} />);
    for (const name of ["Fridge", "Dairy"]) {
      const { className } = screen.getByText(name);
      expect(className).not.toContain("uppercase");
      expect(className).not.toContain("tracking-tight");
      expect(className).toContain("[word-spacing:0.15em]");
    }
  });

  it("renders category names", () => {
    render(<StatsDistributionGrid {...props} />);
    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.getByText("Veggies")).toBeInTheDocument();
  });

  it("renders item counts for storages", () => {
    render(<StatsDistributionGrid {...props} />);
    expect(screen.getAllByText(/\b20\b/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\b30\b/).length).toBeGreaterThan(0);
  });

  it("shows empty state when storageStats is empty", () => {
    render(
      <StatsDistributionGrid
        {...props}
        storageStats={[]}
        maxStorageCount={0}
      />,
    );
    // Distribution section renders without storage rows
    expect(screen.queryByText("Fridge")).not.toBeInTheDocument();
  });

  it("hides the category value when the profile does not show stock value", () => {
    const { container } = render(
      <StatsDistributionGrid {...props} showInventoryValue={false} />,
    );
    // The money is the business metric this profile turned off; the counts
    // the bars are drawn from answer the same question and stay.
    expect(container.textContent ?? "").not.toMatch(/50\.00/);
    expect(container.textContent ?? "").not.toMatch(/30\.00/);
    expect(screen.getAllByText(/\b10\b/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\b15\b/).length).toBeGreaterThan(0);
  });

  it("shows the category value when the setting is on", () => {
    const { container } = render(
      <StatsDistributionGrid {...props} showInventoryValue />,
    );
    expect(container.textContent ?? "").toMatch(/50\.00/);
  });

  it("orders categories by the figure the reader can see", () => {
    // While money is on, the biggest spender leads; with it off, ordering by
    // a hidden amount would put the rows in an order nothing on screen
    // explains, so the count the bars already use takes over.
    const { container, rerender } = render(
      <StatsDistributionGrid {...props} showInventoryValue />,
    );
    const text = () => container.textContent ?? "";
    expect(text().indexOf("Dairy")).toBeLessThan(text().indexOf("Veggies"));

    rerender(<StatsDistributionGrid {...props} showInventoryValue={false} />);
    expect(text().indexOf("Veggies")).toBeLessThan(text().indexOf("Dairy"));
  });

  it("lists places fullest first, empty ones last", () => {
    const places = [
      {
        ...storageStats[0],
        location_id: "e",
        location_name: "Spare",
        items_count: 0,
      },
      storageStats[0],
      storageStats[1],
    ];
    const { container } = render(
      <StatsDistributionGrid {...props} storageStats={places} />,
    );
    const text = container.textContent ?? "";
    expect(text.indexOf("Pantry")).toBeLessThan(text.indexOf("Fridge"));
    expect(text.indexOf("Fridge")).toBeLessThan(text.indexOf("Spare"));
  });

  it("counts stock rows as records, never as pieces", () => {
    // One product held as 2 pcs plus a half-used carton is two rows; the
    // old label printed that as "2 pcs." and read as a total quantity.
    const { container } = render(
      <StatsDistributionGrid
        {...props}
        storageStats={[{ ...storageStats[0], items_count: 2 }]}
        maxStorageCount={2}
        categoryStats={[{ ...categoryStats[0], items_count: 1 }]}
        maxCategoryCount={1}
      />,
    );
    expect(container.textContent).toContain("2 records");
    expect(container.textContent).toContain("1 record");
    expect(container.textContent).not.toMatch(/pcs/i);
  });

  it("names the uncategorised bucket in the reader's language", async () => {
    await withLanguage("pl", () => {
      render(
        <StatsDistributionGrid
          {...props}
          t={tFor("stats")}
          categoryStats={[
            {
              ...categoryStats[0],
              category_id: null,
              category_code: null,
              category_name: "Uncategorized",
            },
          ]}
        />,
      );
      expect(screen.getByText("Brak kategorii")).toBeInTheDocument();
      expect(screen.queryByText("Uncategorized")).not.toBeInTheDocument();
    });
  });
});

// ── StatsOverviewTab ──────────────────────────────────────────────────────────

describe("StatsOverviewTab", () => {
  const tabProps = {
    t,
    overview,
    storageStats,
    categoryStats,
    expiryForecast,
    costAnalysis,
    failures: [],
    attentionCounts,
    showDetails: true,
    onToggleDetails: vi.fn(),
    tracksExpiry: true,
  };

  it("hides every value surface when the profile does not show stock value", () => {
    const { container } = render(
      wrap(<StatsOverviewTab {...tabProps} showInventoryValue={false} />),
    );
    // All of Cost analysis is money — spent, wasted, the category rows, the
    // trend — so the whole section goes rather than a heading over nothing.
    expect(
      screen.queryByText(enStats.costAnalysis.title),
    ).not.toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/50\.00/);
    // The health card's total goes with the rest.
    expect(container.textContent ?? "").not.toMatch(/1,250/);
  });

  it("shows the value surfaces when the setting is on", () => {
    const { container } = render(
      wrap(<StatsOverviewTab {...tabProps} showInventoryValue />),
    );
    expect(screen.getByText(enStats.costAnalysis.title)).toBeInTheDocument();
    expect(container.textContent ?? "").toMatch(/50\.00/);
    expect(container.textContent ?? "").toMatch(/1,250/);
  });

  it("reads a value the server calls unknown as unknown", () => {
    const { container } = render(
      wrap(
        <StatsOverviewTab
          {...tabProps}
          overview={{
            ...tabProps.overview,
            total_value: 0,
            value_known: false,
          }}
          showInventoryValue
        />,
      ),
    );
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/\$0\.00/);
  });
});

// ── StatsExpiryForecast ───────────────────────────────────────────────────────

describe("StatsExpiryForecast", () => {
  it("renders all forecast periods", () => {
    render(<StatsExpiryForecast t={t} expiryForecast={expiryForecast} />);
    // Count values
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders empty state when forecast is empty array", () => {
    render(<StatsExpiryForecast t={t} expiryForecast={[]} />);
    // No count numbers rendered
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("shows Expired period translated label", () => {
    render(<StatsExpiryForecast t={t} expiryForecast={expiryForecast} />);
    expect(screen.getByText("Expired")).toBeInTheDocument();
  });

  it("labels every period with a word, not with its key", () => {
    // Three of the six tiles read DASHBOARD.TODAY, DASHBOARD.TOMORROW and
    // DASHBOARD.NEXT2WEEKS: the component maps the backend's period names onto
    // dashboard.* keys, and three of those keys were in no catalog. The irony
    // of the mechanism is that an UNHANDLED period falls through to the
    // English word from the backend -- only the handled ones could break.
    render(
      <StatsExpiryForecast
        t={t}
        expiryForecast={[
          { period: "Expired", count: 1 },
          { period: "Today", count: 2 },
          { period: "Tomorrow", count: 3 },
          { period: "This week", count: 4 },
          { period: "Next 2 weeks", count: 5 },
          { period: "This month", count: 6 },
        ]}
      />,
    );

    for (const label of [
      "Expired",
      "Today",
      "Tomorrow",
      "This week",
      "Next 2 weeks",
      "This month",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.queryByText(/^dashboard\./i)).not.toBeInTheDocument();
  });

  it("translates the three periods that used to have no key", async () => {
    await withLanguage("pl", async () => {
      render(
        <StatsExpiryForecast
          t={tFor("stats")}
          expiryForecast={[
            { period: "Today", count: 2 },
            { period: "Tomorrow", count: 3 },
            { period: "Next 2 weeks", count: 5 },
          ]}
        />,
      );

      expect(screen.getByText("Dzisiaj")).toBeInTheDocument();
      expect(screen.getByText("Jutro")).toBeInTheDocument();
      expect(screen.getByText("Najbliższe 2 tygodnie")).toBeInTheDocument();
    });
  });
});

// ── ExpenseForecastChart ──────────────────────────────────────────────────────

describe("ExpenseForecastChart", () => {
  it("renders predicted_spending value", () => {
    render(<ExpenseForecastChart data={expenseForecast} t={t} />);
    expect(screen.getByText(/180/)).toBeInTheDocument();
  });

  it("renders historical_avg value", () => {
    render(<ExpenseForecastChart data={expenseForecast} t={t} />);
    expect(screen.getByText(/160/)).toBeInTheDocument();
  });

  it("renders increasing trend icon (TrendingUp svg)", () => {
    render(<ExpenseForecastChart data={expenseForecast} t={t} />);
    expect(document.querySelector("svg")).toBeTruthy();
  });

  it("renders decreasing trend for decreasing data", () => {
    render(
      <ExpenseForecastChart
        data={{ ...expenseForecast, trend: "decreasing" }}
        t={t}
      />,
    );
    // No crash, renders svg icon
    expect(document.querySelector("svg")).toBeTruthy();
  });

  it("renders stable trend for stable data", () => {
    render(
      <ExpenseForecastChart
        data={{ ...expenseForecast, trend: "stable" }}
        t={t}
      />,
    );
    expect(document.querySelector("svg")).toBeTruthy();
  });

  /**
   * With less history than the forecast needs, the three cards showed a zero,
   * the same zero again under a different label, and a confidence bar at 0%.
   * Three numbers where the answer is one sentence.
   */
  it("says how much history is missing instead of predicting nothing", () => {
    render(
      <ExpenseForecastChart
        data={{
          ...expenseForecast,
          trend: "no_data",
          predicted_spending: 0,
          historical_avg: 0,
          confidence: 0,
          weeks_of_data: 2,
          weeks_required: 6,
        }}
        t={t}
      />,
    );

    expect(
      screen.getByText("Not enough purchase history to forecast"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("2 of 6 weeks of purchase history"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("still reports what was thrown away", () => {
    render(
      <ExpenseForecastChart
        data={{
          ...expenseForecast,
          trend: "no_data",
          weeks_of_data: 1,
          weeks_required: 6,
        }}
        t={t}
      />,
    );

    expect(screen.getByText("Waste reduction potential")).toBeInTheDocument();
  });

  // Every figure the forecast offers is money — the prediction, the average
  // behind it and the savings it projects — and the trend and the confidence
  // bar only describe those withheld amounts; the section goes whole.
  it("renders nothing where the profile does not show stock value", () => {
    const { container } = render(
      <ExpenseForecastChart
        data={expenseForecast}
        t={t}
        showInventoryValue={false}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

// ── SmartAlertsPanel ──────────────────────────────────────────────────────────

describe("SmartAlertsPanel", () => {
  it("renders alert item names", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("Bread")).toBeInTheDocument();
  });

  it("renders total_alerts count badge", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("says what the forgotten-items tile counts, so a zero beside a stale row is not a contradiction", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(
      screen.getByText("Untouched for 60 days or more"),
    ).toBeInTheDocument();
  });

  it("says what the total counts, so it is not read against the overview's number", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(
      screen.getByText(
        "Dates, forgotten products, missing staples; not low stock",
      ),
    ).toBeInTheDocument();
  });

  it("says when an expired record went off", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(screen.getByText(/^Expired on .*2026\.$/)).toBeInTheDocument();
  });

  it("leads from an item's alert to that item", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(screen.getByRole("link", { name: "Cheddar" })).toHaveAttribute(
      "href",
      "/inventory/items?open=cheddar-id",
    );
    expect(screen.getByRole("link", { name: "Milk" })).toHaveAttribute(
      "href",
      "/inventory/items?open=milk-id",
    );
    // An alert about a product to buy has no record to open.
    expect(
      screen.queryByRole("link", { name: "Coffee" }),
    ).not.toBeInTheDocument();
  });

  it("writes each alert's sentence in English", () => {
    render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
    expect(screen.getByText(/^Expires on .*2026\.$/)).toBeInTheDocument();
    expect(
      screen.getByText("Untouched for 75 days — use it before buying more."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Last bought 22 days ago, more than twice as long as usual.",
      ),
    ).toBeInTheDocument();
  });

  it.each(["en", "pl", "de", "fr", "es", "pt"] as const)(
    "gives every alert a sentence in %s",
    async (language) => {
      await withLanguage(language, () => {
        render(wrap(<SmartAlertsPanel alerts={smartAlerts} t={t} />));
        for (const alert of smartAlerts.alerts) {
          // The sentence is the line under the product's name.
          const sentence =
            screen.getByText(alert.item_name ?? "").nextElementSibling
              ?.textContent ?? "";
          expect(sentence.trim()).not.toBe("");
          expect(sentence).not.toMatch(/analytics\.alerts|{{/);
        }
      });
    },
  );

  it("renders empty state when no alerts", () => {
    render(
      wrap(<SmartAlertsPanel alerts={{ alerts: [], total_alerts: 0 }} t={t} />),
    );
    expect(screen.queryByText("Milk")).not.toBeInTheDocument();
  });
});

// ── RotationAnalysisCard ──────────────────────────────────────────────────────

describe("RotationAnalysisCard", () => {
  it("renders average_stock_age_days", () => {
    render(<RotationAnalysisCard data={rotationAnalysis} t={t} />);
    expect(screen.getByText("14.5")).toBeInTheDocument();
  });

  it("renders slow_movers_count", () => {
    render(<RotationAnalysisCard data={rotationAnalysis} t={t} />);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders dead_stock_count", () => {
    render(<RotationAnalysisCard data={rotationAnalysis} t={t} />);
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders category name in rotation_by_category", () => {
    render(<RotationAnalysisCard data={rotationAnalysis} t={t} />);
    expect(screen.getByText("Dairy")).toBeInTheDocument();
  });

  it("prints a zero-day category age as the number it is", () => {
    // The row kept the truthiness guard the tiles had lost: a server-sent
    // 0.0 read as no movement while the tiles printed 0.0 — one quantity,
    // two sentences, two hundred pixels apart.
    render(
      <RotationAnalysisCard
        data={{
          ...rotationAnalysis,
          rotation_by_category: [
            {
              category_name: "Uncategorized",
              item_count: 583,
              average_days: 0,
            },
          ],
        }}
        t={t}
      />,
    );

    expect(screen.getByText(/0\.0/)).toBeInTheDocument();
    expect(screen.queryByText("No movement yet")).not.toBeInTheDocument();
  });

  it("says no movement for a category whose age is unknown", () => {
    render(
      <RotationAnalysisCard
        data={{
          ...rotationAnalysis,
          rotation_by_category: [
            {
              category_name: "Uncategorized",
              item_count: 583,
              average_days: null,
            },
          ],
        }}
        t={t}
      />,
    );

    expect(screen.getByText("No movement yet")).toBeInTheDocument();
  });

  /**
   * The rows carry the seed's English name and the code the reader's
   * language names the category by. The card printed the name as it came,
   * so it said "Deli" a tab away from "Cold cuts" everywhere else — in the
   * category rows and in both stock lists.
   */
  it("names a seeded category the way every other screen does", async () => {
    const salami = {
      item_id: "i1",
      name: "Salami",
      brand: null,
      category: "Deli",
      category_code: "deli",
      value: 20,
      quantity: 2,
      location: "Shelf A",
    };
    const data: RotationAnalysis = {
      ...rotationAnalysis,
      rotation_by_category: [
        {
          category_name: "Deli",
          category_code: "deli",
          item_count: 2,
          average_days: 70,
        },
      ],
      slow_movers: [{ ...salami, days_in_storage: 40 }],
      dead_stock: [{ ...salami, item_id: "i2", days_in_storage: 100 }],
    };

    const { unmount } = render(<RotationAnalysisCard data={data} t={t} />);
    expect(screen.getAllByText("Cold cuts")).toHaveLength(3);
    expect(screen.queryByText("Deli")).not.toBeInTheDocument();
    unmount();

    await withLanguage("pl", () => {
      render(<RotationAnalysisCard data={data} t={tFor("stats")} />);
      expect(screen.getAllByText("Wędliny")).toHaveLength(3);
    });
  });

  // The home profile presets `show_inventory_value` off: the ages and the
  // counts answer how long stock stands, not what it is worth, so only the
  // one figure that is money goes with the setting.
  it("hides the dead-stock value when the profile does not show stock value", () => {
    const { container } = render(
      <RotationAnalysisCard
        data={rotationAnalysis}
        t={t}
        showInventoryValue={false}
      />,
    );

    expect(screen.getByText("14.5")).toBeInTheDocument();
    expect(
      screen.queryByText(enStats.analytics.rotation.deadStockValue),
    ).not.toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/15\.50/);
  });

  it("shows the dead-stock value when the setting is on", () => {
    const { container } = render(
      <RotationAnalysisCard data={rotationAnalysis} t={t} showInventoryValue />,
    );

    expect(
      screen.getByText(enStats.analytics.rotation.deadStockValue),
    ).toBeInTheDocument();
    expect(container.textContent ?? "").toMatch(/15\.50/);
  });
});

// ── PurchasePatternsGrid ──────────────────────────────────────────────────────

describe("PurchasePatternsGrid", () => {
  it("renders recurring product names", () => {
    render(<PurchasePatternsGrid data={purchasePatterns} t={t} />);
    expect(screen.getByText("Milk")).toBeInTheDocument();
  });

  it("renders product brand", () => {
    render(<PurchasePatternsGrid data={purchasePatterns} t={t} />);
    expect(screen.getByText("FarmFresh")).toBeInTheDocument();
  });

  it("renders seasonal product names", () => {
    render(<PurchasePatternsGrid data={purchasePatterns} t={t} />);
    expect(screen.getByText("Strawberries")).toBeInTheDocument();
  });

  it("renders bulk opportunity product names", () => {
    render(<PurchasePatternsGrid data={purchasePatterns} t={t} />);
    expect(screen.getByText("Rice")).toBeInTheDocument();
  });

  it("names a recurring product's seeded category through its code", async () => {
    // Same row shape, same fault as the rotation card: the category came as
    // the seed's English name and was printed as it came.
    const data: PurchasePatterns = {
      ...purchasePatterns,
      top_recurring_products: [
        {
          ...purchasePatterns.top_recurring_products[0],
          category: "Deli",
          category_code: "deli",
        },
      ],
    };

    const { unmount } = render(<PurchasePatternsGrid data={data} t={t} />);
    expect(screen.getByText("Cold cuts")).toBeInTheDocument();
    expect(screen.queryByText("Deli")).not.toBeInTheDocument();
    unmount();

    await withLanguage("pl", () => {
      render(<PurchasePatternsGrid data={data} t={tFor("stats")} />);
      expect(screen.getByText("Wędliny")).toBeInTheDocument();
    });
  });

  it("renders empty state when no recurring products", () => {
    render(
      <PurchasePatternsGrid
        data={{ ...purchasePatterns, top_recurring_products: [] }}
        t={t}
      />,
    );
    expect(screen.queryByText("Milk")).not.toBeInTheDocument();
  });

  /**
   * Four labels in this file asked for `analytics.patterns.*` without a
   * namespace, so i18next looked in `stats`, found nothing, and quietly
   * rendered the English `defaultValue` next to Polish headings. The
   * translations were in `common` all along.
   */
  it("translates its labels rather than falling back to English", async () => {
    await withLanguage("pl", () => {
      render(
        <PurchasePatternsGrid data={purchasePatterns} t={tFor("stats")} />,
      );

      expect(screen.getByText("Śr. cena")).toBeInTheDocument();
      expect(screen.getByText("Łączne wydatki")).toBeInTheDocument();
      expect(screen.queryByText("Avg price")).not.toBeInTheDocument();
      expect(screen.queryByText("Total spent")).not.toBeInTheDocument();
    });
  });

  it("does not call one month of history a hundred-percent season", () => {
    render(
      <PurchasePatternsGrid
        data={{
          ...purchasePatterns,
          seasonal_products: [
            {
              ...purchasePatterns.seasonal_products[0],
              seasonality_score: null,
            },
          ],
        }}
        t={t}
      />,
    );

    expect(screen.getByText("Too few seasons")).toBeInTheDocument();
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
  });

  // Prices are the business metric this profile turned off; what recurs, in
  // which season and in what quantity does not depend on them.
  it("drops the prices and keeps the patterns when the profile hides stock value", () => {
    const { container } = render(
      <PurchasePatternsGrid
        data={purchasePatterns}
        t={t}
        showInventoryValue={false}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/2\.50/); // Avg. price
    expect(text).not.toMatch(/30\.00/); // Total spent
    expect(text).not.toMatch(/3\.00/); // Unit price per kg
    expect(text).not.toMatch(/15\.00/); // Potential savings
    // The pattern itself stays.
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("12x")).toBeInTheDocument();
    expect(screen.getByText("Strawberries")).toBeInTheDocument();
    expect(screen.getByText("Rice")).toBeInTheDocument();
  });

  it("shows the prices when the setting is on", () => {
    const { container } = render(
      <PurchasePatternsGrid data={purchasePatterns} t={t} showInventoryValue />,
    );

    const text = container.textContent ?? "";
    expect(text).toMatch(/2\.50/);
    expect(text).toMatch(/30\.00/);
    expect(text).toMatch(/15\.00/);
  });
});
