import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { BrowserRouter, MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatsPage from "./StatsPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

const Wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = createQueryClient();
  return (
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <BrowserRouter>{children}</BrowserRouter>
        </ModulesProvider>
      </QueryClientProvider>
    </PageHeaderContext.Provider>
  );
};

// The analytics tab and the value switch are independent checkboxes on the
// module settings screen, so a profile can want the first and refuse the
// second — these payloads give every analytics surface something to show.
const analyticsRotation = {
  average_stock_age_days: 14.5,
  median_stock_age_days: 12,
  consumed_items_count: 9,
  slow_movers_count: 3,
  dead_stock_count: 1,
  dead_stock_value: 15.5,
  slow_movers: [],
  dead_stock: [],
  rotation_by_category: [],
};

const analyticsForecast = {
  forecast_period: "month",
  predicted_spending: 180,
  historical_avg: 160,
  trend: "increasing",
  waste_reduction_potential: 20,
  confidence: 0.75,
  weeks_of_data: 9,
  weeks_required: 6,
};

const analyticsPatterns = {
  top_recurring_products: [
    {
      name: "Milk",
      brand: "FarmFresh",
      category: "Dairy",
      total_purchases_last_6_months: 12,
      avg_price: 2.5,
      avg_quantity: 1,
      total_spent: 30,
    },
  ],
  seasonal_products: [],
  bulk_opportunities: [],
};

const renderAnalytics = (showInventoryValue: boolean) => {
  server.use(
    http.get("/api/v1/stats/config", () =>
      HttpResponse.json({
        enable_analytics: true,
        show_inventory_value: showInventoryValue,
      }),
    ),
    http.get("/api/v1/stats/rotation-analysis", () =>
      HttpResponse.json(analyticsRotation),
    ),
    http.get("/api/v1/stats/smart-alerts", () =>
      HttpResponse.json({ alerts: [], total_alerts: 0 }),
    ),
    http.get("/api/v1/stats/expense-forecast", () =>
      HttpResponse.json(analyticsForecast),
    ),
    http.get("/api/v1/stats/purchase-patterns", () =>
      HttpResponse.json(analyticsPatterns),
    ),
  );

  const queryClient = createQueryClient();
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter initialEntries={["/inventory/stats/analytics"]}>
            <StatsPage />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
};

describe("StatsPage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "stats", "items", "locations"]),
      ),
      http.get("/api/v1/stats/overview", () =>
        HttpResponse.json({
          total_items: 10,
          // Stock value now travels on the overview, summed over the items —
          // the by-category subtotals below are a different question.
          total_value: 30.0,
          // Deliberately not the attention numbers: the health card and the
          // expiry tiles read the one counts endpoint below, so a page that
          // still computed from here would show 70 instead of 7.
          expiring_soon: 20,
          expired: 10,
          low_stock: 40,
          currency: "PLN",
        }),
      ),
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json({
          expired: 1,
          expiring_soon: 2,
          low_stock: 4,
          records: 7,
        }),
      ),
      http.get("/api/v1/stats/by-location", () =>
        HttpResponse.json([
          { location_name: "Fridge", items_count: 5, total_value: 50.0 },
        ]),
      ),
      http.get("/api/v1/stats/by-category", () =>
        HttpResponse.json([
          { category_name: "Dairy", items_count: 3, total_value: 30.0 },
        ]),
      ),
      http.get("/api/v1/stats/expiry-forecast", () => HttpResponse.json([])),
      http.get("/api/v1/stats/cost-analysis", () =>
        HttpResponse.json({
          total_spent: 500,
          total_wasted: 50,
          waste_event_rate: 10,
          savings_opportunities: [],
        }),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/locations/tree", () =>
        HttpResponse.json([
          {
            id: "loc-1",
            name: "Cold Storage",
            parent_id: null,
            usage: "internal",
            location_type_id: "type-fridge",
            short_code: null,
            context_tag: null,
            items_count: 5,
            children: [],
          },
        ]),
      ),
      http.get("/api/v1/location-types", () =>
        HttpResponse.json(
          onePage([
            {
              id: "type-fridge",
              name: "Cold Storage",
              type_code: "cold_storage",
              behavior_mode: "EXPIRY",
              icon: null,
              default_settings: null,
              context_schema: [],
            },
          ]),
        ),
      ),
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "1", currency: "PLN", name: "Test Org" }),
      ),
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({ enable_analytics: true }),
      ),
    );
  });

  it("should render stats health card after data loads", async () => {
    render(<StatsPage />, { wrapper: Wrapper });

    // One count, from the one endpoint: the records behind its list, not
    // the overview's 20+10+40.
    expect(await screen.findByText("7")).toBeInTheDocument();
  });

  it("should render overview cards", async () => {
    render(<StatsPage />, { wrapper: Wrapper });

    // Wait for health card to render
    expect(await screen.findByText("7")).toBeInTheDocument();
    // totalInventoryValue comes from the overview now, formatted with the
    // organization currency (PLN). The card reads that currency itself, so
    // the amount lands one tick after the count beside it.
    expect(await screen.findByText("PLN 30.00")).toBeInTheDocument();
  });

  it("should render distribution sections", async () => {
    render(<StatsPage />, { wrapper: Wrapper });

    // Wait for page content to load
    expect(await screen.findByText("7")).toBeInTheDocument();
    // The toggle button is visible by default
    expect(screen.getByText("Show detailed stats")).toBeInTheDocument();
  });

  describe("tab bar", () => {
    afterEach(() => signOut());

    it("scrolls its tabs in a track of their own and keeps the module settings link outside it", async () => {
      // On a phone the fourth tab pushed the settings link off the edge with
      // nothing to say there was more. The tabs now sit in a ScrollRow, whose
      // edge fade is that signal, and the link stands beside the track.
      signInWith(["admin:access"]);
      render(<StatsPage />, { wrapper: Wrapper });

      const settings = await screen.findByRole("link", {
        name: /module settings/i,
      });
      const overview = screen.getByRole("link", { name: /overview/i });
      const track = overview.parentElement as HTMLElement;
      expect(track.className).toContain("overflow-x-auto");
      expect(track).not.toContainElement(settings);
      expect(track.parentElement).toContainElement(settings);
    });
  });

  // Analytics is a per-profile feature.
  it("shows the analytics tab when the module config enables it", async () => {
    render(<StatsPage />, { wrapper: Wrapper });

    expect(await screen.findByText("Analytics")).toBeInTheDocument();
  });

  it("hides the analytics tab when the module config disables it", async () => {
    server.use(
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({ enable_analytics: false }),
      ),
    );
    render(<StatsPage />, { wrapper: Wrapper });

    // Page settled (health card up) and the tab is gone.
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.queryByText("Analytics")).not.toBeInTheDocument();
  });

  // The overview's value signal follows the module setting the
  // profile presets: off on the home profile, where no cost ledger backs it.
  it("hides the inventory value when the module config disables it", async () => {
    server.use(
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({
          enable_analytics: true,
          show_inventory_value: false,
        }),
      ),
    );
    render(<StatsPage />, { wrapper: Wrapper });

    // The page settled: the "needs attention" signal is up, the business
    // metric is not offered.
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.queryByText("PLN 30.00")).not.toBeInTheDocument();
    expect(screen.getByText(/2 signals/i)).toBeInTheDocument();
  });

  it("redirects /inventory/stats/analytics to the overview when disabled", async () => {
    server.use(
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({ enable_analytics: false }),
      ),
    );
    // MemoryRouter because the global test setup resets window.location
    // after each test, which breaks history.pushState in this environment.
    const LocationProbe = () => {
      const location = useLocation();
      return <div data-testid="location-probe">{location.pathname}</div>;
    };
    const queryClient = createQueryClient();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <MemoryRouter initialEntries={["/inventory/stats/analytics"]}>
              <LocationProbe />
              <StatsPage />
            </MemoryRouter>
          </ModulesProvider>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    // The gate lands back on the overview — the health card renders, and the
    // location leaves the analytics route.
    expect(await screen.findByText("7")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toBe(
        "/inventory/stats",
      ),
    );
  });

  it("hides the analytics money surfaces when the profile does not show stock value", async () => {
    renderAnalytics(false);

    // Settled on the pattern rows: their counts and names stay.
    expect(await screen.findByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("12x")).toBeInTheDocument();
    // Rotation keeps its ages; its one money card goes.
    expect(screen.getByText("14.5")).toBeInTheDocument();
    expect(screen.queryByText("Dead stock value")).not.toBeInTheDocument();
    // The expense forecast is money end to end.
    expect(screen.queryByText("Predicted spending")).not.toBeInTheDocument();
    // Purchase patterns keep the patterns, lose the prices.
    expect(screen.queryByText("Avg. price")).not.toBeInTheDocument();
    expect(screen.queryByText("Total spent")).not.toBeInTheDocument();
  });

  it("shows the analytics money surfaces when the setting is on", async () => {
    renderAnalytics(true);

    expect(await screen.findByText("Predicted spending")).toBeInTheDocument();
    expect(screen.getByText("Dead stock value")).toBeInTheDocument();
    expect(screen.getByText("Avg. price")).toBeInTheDocument();
  });
});
