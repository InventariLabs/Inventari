import React from "react";
import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import InventoryDashboard from "../pages/InventoryDashboard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

/**
 * Two assets once produced a "2 products" tile above a list reading "0
 * results": the stats overview counts every item in every internal
 * location, while the products list hides what a vertical module owns. The
 * count now sits in the attention card's status line and still has to be
 * the list's own — and it says "records", as the list does, because one
 * product held in two places is two of its rows.
 */
describe("the records count and the list underneath it", () => {
  it("counts the rows the list will show, not every item in storage", async () => {
    let askedToHideModuleData: string | null = null;
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 5,
          has_more: false,
        }),
      ),
      http.get("/api/v1/stats/overview", () =>
        HttpResponse.json({ total_items: 7 }),
      ),
      http.get("/api/v1/items", ({ request }) => {
        const p = new URL(request.url).searchParams;
        if (p.get("limit") === "1") {
          askedToHideModuleData = p.get("exclude_module_contexts");
        }
        return HttpResponse.json({
          items: [],
          total: p.get("limit") === "1" ? 5 : 0,
          offset: 0,
          limit: Number(p.get("limit")),
          has_more: false,
        });
      }),
    );

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    expect(await screen.findByText(/^In all: 5 records/)).toBeInTheDocument();
    expect(screen.queryByText(/^In all: 7 records/)).toBeNull();
    expect(askedToHideModuleData).toBe("true");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
  });

  it("counts one product held as two records as two records", async () => {
    const row = (id: string, quantity: string) => ({
      id,
      name: "Milk 3.2% 1 l",
      quantity,
      expiry_date: "2026-10-31",
    });
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 5,
          has_more: false,
        }),
      ),
      http.get("/api/v1/items", ({ request }) => {
        const p = new URL(request.url).searchParams;
        return HttpResponse.json({
          items: [row("a", "2.0000"), row("b", "0.5000")],
          total: 2,
          offset: 0,
          limit: Number(p.get("limit")),
          has_more: false,
        });
      }),
    );

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    expect(await screen.findByText(/^In all: 2 records/)).toBeInTheDocument();
    expect(screen.queryByText(/\d+ products/)).toBeNull();
  });

  it("says the count stopped where a large organization's list stops counting", async () => {
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 5,
          has_more: false,
        }),
      ),
      http.get("/api/v1/items", ({ request }) => {
        const p = new URL(request.url).searchParams;
        return HttpResponse.json({
          items: [],
          total: 10000,
          offset: 0,
          limit: Number(p.get("limit")),
          has_more: true,
          total_capped: true,
        });
      }),
    );

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    expect(
      await screen.findByText(/^In all: more than 10000 records/),
    ).toBeInTheDocument();
  });
});
