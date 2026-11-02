import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ValuationCard } from "../components/ValuationCard";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { withLanguage } from "@/test/mocks/i18n";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockValuation = {
  item_id: "item-1",
  item_name: "ThinkPad X1",
  serial_number: "SN-001",
  purchase_price: 1200.0,
  book_value: 960.0,
  depreciation_pct: 20.0,
  useful_life_years: 5,
  is_depreciable: true,
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>{children}</ModulesProvider>
    </QueryClientProvider>
  );
};

describe("ValuationCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state", async () => {
    server.use(
      http.get("/api/v1/equipment/item-1/valuation", async () => {
        await new Promise((r) => setTimeout(r, 5000));
        return HttpResponse.json(mockValuation);
      }),
    );

    render(<ValuationCard itemId="item-1" />, { wrapper: createWrapper() });
    expect(await screen.findByText("Loading…")).toBeInTheDocument();
  });

  it("renders valuation data when depreciable", async () => {
    server.use(
      http.get("/api/v1/equipment/item-1/valuation", () =>
        HttpResponse.json(mockValuation),
      ),
    );

    render(<ValuationCard itemId="item-1" />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Purchase Price")).toBeInTheDocument();
    });
    expect(screen.getByText(/1,200\.00/)).toBeInTheDocument();
    expect(screen.getByText(/960\.00/)).toBeInTheDocument();
    // The API reports tenths ("20.0"); the card keeps the digit and writes
    // it the way the interface language does.
    expect(screen.getByText("20.0%")).toBeInTheDocument();
  });

  it("writes the depreciation percent the way the reader's language does", async () => {
    await withLanguage("pl", async () => {
      server.use(
        http.get("/api/v1/equipment/item-1/valuation", () =>
          HttpResponse.json({ ...mockValuation, depreciation_pct: "12.5" }),
        ),
      );

      render(<ValuationCard itemId="item-1" />, { wrapper: createWrapper() });

      expect(await screen.findByText("12,5%")).toBeInTheDocument();
      expect(screen.queryByText("12.5%")).not.toBeInTheDocument();
    });
  });

  it("renders nothing when not depreciable", async () => {
    server.use(
      http.get("/api/v1/equipment/item-2/valuation", () =>
        HttpResponse.json({
          item_id: "item-2",
          item_name: "Free Item",
          serial_number: null,
          purchase_price: null,
          book_value: 0,
          depreciation_pct: 0,
          useful_life_years: 5,
          is_depreciable: false,
        }),
      ),
    );

    const { container } = render(<ValuationCard itemId="item-2" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });

  it("renders useful life label", async () => {
    server.use(
      http.get("/api/v1/equipment/item-1/valuation", () =>
        HttpResponse.json(mockValuation),
      ),
    );

    render(<ValuationCard itemId="item-1" />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Useful Life")).toBeInTheDocument();
    });
  });
});
