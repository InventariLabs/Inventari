import React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { FleetValuationWidget } from "../components/FleetValuationWidget";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockFleetValuation = {
  total_purchase_value: 5000,
  total_book_value: 3500,
  total_depreciation: 1500,
  by_category: [
    {
      category_name: "Laptop",
      purchase_value: 3000,
      book_value: 2100,
      depreciation: 900,
      asset_count: 3,
      depreciable_count: 3,
    },
    {
      category_name: "Monitor",
      purchase_value: 2000,
      book_value: 1400,
      depreciation: 600,
      asset_count: 2,
      depreciable_count: 2,
    },
  ],
  asset_count: 5,
  depreciable_count: 5,
  excluded_count: 0,
};

const emptyFleetValuation = {
  total_purchase_value: 0,
  total_book_value: 0,
  total_depreciation: 0,
  by_category: [],
  asset_count: 0,
  depreciable_count: 0,
  excluded_count: 0,
};

/**
 * The reported case: a new laptop carries a purchase price but
 * no purchase date or useful life, so there is no book value to strike —
 * the widget must not print 0.00 as if there were.
 */
const unconfiguredFleetValuation = {
  total_purchase_value: 5400,
  total_book_value: 0,
  total_depreciation: 0,
  by_category: [
    {
      category_name: "Laptop",
      purchase_value: 5400,
      book_value: 0,
      depreciation: 0,
      asset_count: 1,
      depreciable_count: 0,
    },
  ],
  asset_count: 1,
  depreciable_count: 0,
  excluded_count: 0,
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ModulesProvider>{children}</ModulesProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe("FleetValuationWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an error and a retry when valuation cannot be loaded", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    render(<FleetValuationWidget />, { wrapper: createWrapper() });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("flags valued assets that have no status", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json({
          ...mockFleetValuation,
          no_status_count: 2,
          no_status_assets: [{ id: "asset-1", name: "Laptop A" }],
        }),
      ),
    );
    render(<FleetValuationWidget />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("2 valued assets have no status"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Laptop A" })).toHaveAttribute(
      "href",
      "/equipment/asset-1",
    );
  });

  it("renders fleet valuation summary", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(mockFleetValuation),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Fleet Valuation")).toBeInTheDocument();
    });
    expect(screen.getByText(/5,000\.00/)).toBeInTheDocument();
    expect(screen.getByText(/3,500\.00/)).toBeInTheDocument();
    expect(screen.getByText(/1,500\.00/)).toBeInTheDocument();
  });

  it("renders category breakdown table", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(mockFleetValuation),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Laptop")).toBeInTheDocument();
    });
    expect(screen.getByText("Monitor")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders nothing when no assets", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(emptyFleetValuation),
      ),
    );

    const { container } = render(<FleetValuationWidget />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });

  it("renders an exclusion note for foreign-currency assets", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json({ ...mockFleetValuation, excluded_count: 3 }),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        // Plural forms replaced the "asset(s)" placeholder;
        // the sentence itself was reworded when the exclusion started naming
        // every cause — no price, a foreign currency, or retired.
        screen.getByText(
          /Not included in the totals: 3 assets without a purchase price, priced in another currency, or retired/,
        ),
      ).toBeInTheDocument();
    });
  });

  it("renders header labels", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(mockFleetValuation),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Purchase Value")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Book Value").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Depreciation").length).toBeGreaterThanOrEqual(
      1,
    );
    expect(screen.getByText("By Category")).toBeInTheDocument();
  });

  it("renders table column headers", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(mockFleetValuation),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Category")).toBeInTheDocument();
    });
    // "Valued", not "Count": the column counts the assets that carry value
    // here, and the register's count (the categories catalogue) reads
    // higher whenever one asset is retired, priceless or foreign-currency.
    expect(screen.getByText("Valued")).toBeInTheDocument();
    // Full canonical labels (was: "Book" / "Dep." abbreviations); both the
    // summary block and the table column header render them.
    expect(screen.getAllByText("Book Value")).toHaveLength(2);
    expect(screen.getAllByText("Depreciation")).toHaveLength(2);
  });

  it("hides book value and depreciation when nothing is configured", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(unconfiguredFleetValuation),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Purchase Value")).toBeInTheDocument();
    });
    // The financial figures are absent, not zero: a 0.00 would read as a
    // fact nobody entered.
    expect(screen.queryByText("Book Value")).not.toBeInTheDocument();
    expect(screen.queryByText("Depreciation")).not.toBeInTheDocument();
    expect(
      // A whole zero amount ("PLN 0.00"), not the tail of the purchase
      // value's decimals.
      screen.queryByText((content) => /^[\D]*0\.00$/.test(content.trim())),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/5,400\.00/)).toBeInTheDocument();
    // The reader is told why the columns are missing.
    expect(
      screen.getByText(
        /Book value and depreciation appear for assets with a purchase date and useful life/,
      ),
    ).toBeInTheDocument();
    // The table still breaks down what is known: the category and its count.
    expect(screen.getByText("Laptop")).toBeInTheDocument();
    expect(screen.getByText("Valued")).toBeInTheDocument();
  });

  it("names the assets without a configuration beside the configured ones", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json({
          ...mockFleetValuation,
          asset_count: 7,
          depreciable_count: 5,
        }),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(
          "2 assets without a purchase date or useful life are counted at purchase value only",
        ),
      ).toBeInTheDocument();
    });
  });

  it("shows a dash for a category nothing is configured in", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json({
          total_purchase_value: 6400,
          total_book_value: 2100,
          total_depreciation: 900,
          by_category: [
            {
              category_name: "Laptop",
              purchase_value: 3000,
              book_value: 2100,
              depreciation: 900,
              asset_count: 3,
              depreciable_count: 3,
            },
            {
              category_name: "Monitor",
              purchase_value: 3400,
              book_value: 0,
              depreciation: 0,
              asset_count: 2,
              depreciable_count: 0,
            },
          ],
          asset_count: 5,
          depreciable_count: 3,
          excluded_count: 0,
        }),
      ),
    );

    render(<FleetValuationWidget />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Monitor")).toBeInTheDocument();
    });
    // The Monitor row shows no number — neither 0.00 nor its purchase
    // price — for figures it has no configuration for.
    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.getAllByText("Not configured").length).toBeGreaterThanOrEqual(
      2,
    );
  });
});
