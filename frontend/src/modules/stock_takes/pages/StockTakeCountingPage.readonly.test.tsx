import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import StockTakeCountingPage from "./StockTakeCountingPage";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const completed = {
  id: "1",
  name: "Dry goods count",
  location_id: "1",
  location_name: "Dry Goods",
  status: "completed",
  items_count: 2,
  items: [
    {
      id: "sti-1",
      item_id: "1",
      name: "Flour",
      system_quantity: 2,
      counted_quantity: 2,
      is_discrepancy: 0,
    },
    {
      id: "sti-2",
      item_id: "2",
      name: "Sugar",
      system_quantity: 4,
      counted_quantity: 3,
      is_discrepancy: 1,
    },
  ],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe("StockTakeCountingPage for an account that may not count", () => {
  beforeEach(() => {
    signInWith(["stock_takes:read"]);
    server.use(
      http.get("/api/v1/stock-takes/1", () => HttpResponse.json(completed)),
    );
  });

  it("shows how far the count got and the way to its report, not just a notice", async () => {
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider
                client={
                  new QueryClient({
                    defaultOptions: { queries: { retry: false } },
                  })
                }
              >
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: vi.fn() }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("You can view this, not change it"),
    ).toBeInTheDocument();
    const report = await screen.findByRole("link", { name: /Report/ });
    expect(report).toHaveAttribute("href", "/inventory/stock-takes/1/report");
  });
});
